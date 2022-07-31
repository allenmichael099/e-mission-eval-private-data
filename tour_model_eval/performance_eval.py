# helper functions for evaluating model performance

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import itertools
import logging
import os
from datetime import datetime

import sklearn.metrics as sm
from sklearn.metrics.cluster import contingency_matrix
from sklearn.model_selection import KFold, ParameterGrid

# our imports
import models
from data_wrangling import get_trip_index, get_labels, expand_coords
from clustering import add_loc_clusters, ALG_OPTIONS, purity_score
import emission.analysis.modelling.tour_model_first_only.get_users as gu
import emission.analysis.modelling.tour_model_first_only.data_preprocessing as pp

# TODO: these may require further updating
DEFAULT_MODES = [
    'walk', 'bike', 'e-bike', 'scootershare', 'drove_alone', 'shared_ride',
    'taxi', 'bus', 'train', 'free_shuttle', 'air', 'not_a_trip', 'no pred',
    np.nan
]
DEFAULT_REPLACED = [
    'walk', 'bike', 'e-bike', 'scootershare', 'drove_alone', 'shared_ride',
    'taxi', 'bus', 'train', 'free_shuttle', 'air', 'not_a_trip', 'no pred',
    np.nan, 'same_mode', 'no_travel'
]
DEFAULT_PURPOSES = [
    'home', 'work', 'at_work', 'school', 'transit_transfer', 'shopping',
    'meal', 'pick_drop_person', 'pick_drop_item', 'personal_med',
    'access_recreation', 'exercise', 'entertainment', 'religious',
    'not_a_trip', 'no pred', np.nan
]

RADIUS = 500

PREDICTORS = {
    # key: model name
    # value: (model class, model params)
    'old clustering': (models.OldClusteringPredictor, None),
    'new clustering by end r100m': (models.ClusterOnlyPredictor, {
        'cluster_method': 'end',
        'radius': 100,
    }),
    'new clustering by trip r100m': (models.ClusterOnlyPredictor, {
        'cluster_method': 'trip',
        'radius': 100,
    }),
    'new clustering by combo r100m': (models.ClusterOnlyPredictor, {
        'cluster_method': 'combination',
        'radius': 100,
    }),
    'new clustering by end r150m': (models.ClusterOnlyPredictor, {
        'cluster_method': 'end',
        'radius': 150,
    }),
    'new clustering by trip r150m': (models.ClusterOnlyPredictor, {
        'cluster_method': 'trip',
        'radius': 150,
    }),
    'new clustering by combo r150m': (models.ClusterOnlyPredictor, {
        'cluster_method': 'combination',
        'radius': 150,
    }),
    'random forest with end r100m': (models.ClusterForestPredictor, {
        'use_start_clusters': False,
        'use_trip_clusters': False,
        'drop_unclustered': False,
        'radius': 100,
    }),
    'random forest with end r150m': (models.ClusterForestPredictor, {
        'use_start_clusters': False,
        'use_trip_clusters': False,
        'drop_unclustered': False,
        'radius': 100,
    }),
    'random forest with end and trip r100m': (models.ClusterForestPredictor, {
        'use_start_clusters': False,
        'use_trip_clusters': True,
        'drop_unclustered': False,
        'radius': 100,
    }),
    'random forest with end and trip, drop unclustered r100m':
    (models.ClusterForestPredictor, {
        'use_start_clusters': False,
        'use_trip_clusters': True,
        'drop_unclustered': True,
        'radius': 100,
    }),
    'random forest with end and trip r150m': (models.ClusterForestPredictor, {
        'use_start_clusters': False,
        'use_trip_clusters': True,
        'drop_unclustered': False,
        'radius': 150,
    }),
    'final random forest with clustering': (models.ClusterForestPredictor, {
        'n_estimators': 100,
        'max_depth': None,
        'min_samples_split': 2,
        'min_samples_leaf': 1,
        'max_features': 'sqrt',
        'bootstrap': False,
        'use_start_clusters': False,
        'use_trip_clusters': True,
        'drop_unclustered': False,
        'radius': 150,
    }),
    'random forest with end and trip, drop unclustered r150m':
    (models.ClusterForestPredictor, {
        'use_start_clusters': False,
        'use_trip_clusters': True,
        'drop_unclustered': True,
        'radius': 150,
    }),
    'random forest with start and end r100m': (models.ClusterForestPredictor, {
        'use_start_clusters': True,
        'use_trip_clusters': False,
        'drop_unclustered': False,
        'radius': 100,
    }),
    'random forest with start end trip r100m':
    (models.ClusterForestPredictor, {
        'use_start_clusters': True,
        'use_trip_clusters': True,
        'drop_unclustered': False,
        'radius': 100,
    }),
    'random forest, no clustering': (models.BasicForestPredictor, {}),
    'adaboost basic': (models.ClusterAdaBoostPredictor, {}),
}


def cross_val_predict(model,
                      model_params=None,
                      data_type='dataframe',
                      user_df=None,
                      user=None,
                      k=5,
                      random_state=42,
                      min_samples=False):
    """ Conducts k-fold cross-validation and generates predictions for the entire labeled dataset of a single user.
    
        Concatenates the predictions from each of k folds.
        
        Returns: 
            dict containing lists of ids, predicted labels, true labels, and confidences.
        
        Args: 
            model: a model class with fit() and predict() methods. predict() 
                should return a tuple containing 3 array-like objects of equal length: predicted modes, predicted purposes, and predicted replaced modes.
            data_type (str): either 'list' or 'dataframe', indicating whether 
                the model accepts trips in the form of a list or dataframe. (some  hackery so we can still use OldClusteringPredictor, which takes in a list of trips.)
            user_df (dataframe): dataframe containing 
            user: UUID for a user. only if data_type = 'list'
            k (int): number of folds
            random_state (int): random seed for reproducibility 
            min_samples (bool): whether or not to require a minimum number of 
                trips. If True, the value is determined by gu.valid_user(). If False, we still require a minimum of k trips in order for k-fold cross-validation to work. 
    """
    assert data_type == 'dataframe' or data_type == 'list'
    kfolds = KFold(k, random_state=random_state, shuffle=True)
    idx = []
    # trip_idx = []
    mode_true = []
    mode_pred = []
    purpose_true = []
    purpose_pred = []
    replaced_true = []
    replaced_pred = []
    # confidence = np.empty([0], dtype=int)
    # note: we can't use np arrays or call np.append for any list-like object containing labels because the label elements may be of multiple types (str, for actual labels and np.nan for missing labels).
    # TODO: actually, we should probably change all the np.nan labels to Nonetype instead.

    if data_type == 'dataframe':
        logging.debug(f'num trips {len(user_df)}')
        if not min_samples and len(user_df) < 5:
            logging.info(
                'At least 5 valid trips are needed for cross-validation, user only had {}.'
                .format(len(user_df)))
            return

    elif data_type == 'list':
        trips = pp.read_data(user)

        # keeps valid trips that have user labels and are not points
        filter_trips = np.array(pp.filter_data(trips, RADIUS))
        logging.debug(f'num trips {len(filter_trips)}')

        # valid user should have >= 10 trips for further analysis and the proportion of filter_trips is >=50%
        # todo: we should update this to account for the smaller training set in each fold (80%)
        if min_samples and not gu.valid_user(filter_trips, trips):
            logging.debug(
                f"Total: {len(trips)}, labeled: {len(filter_trips)}, user {user} doesn't have enough valid trips for further analysis."
            )
            return
        elif not min_samples and len(filter_trips) < k:
            logging.debug(
                'At least 5 valid trips are needed for cross-validation, user {} only had {}.'
                .format(user, len(filter_trips)))
            return

    num_trips = len(user_df) if user_df is not None else len(filter_trips)
    for train_idx, test_idx in kfolds.split(np.arange(num_trips)):
        if data_type == 'dataframe':
            # set up model and data
            model_ = model()
            if model_params is not None:
                model_.set_params(model_params)
            train_trips = user_df.iloc[train_idx]
            test_trips = user_df.iloc[test_idx]

            # train the model
            model_.fit(train_trips)

            # generate predictions
            next_mode_pred, next_purpose_pred, next_replaced_pred = model_.predict(
                test_trips)

            # store information on the test trips
            idx = np.append(idx, test_idx)
            # handle case where users input partial labels (e.g. some users
            # never input replaced-mode)
            if 'mode_confirm' in test_trips.columns:
                mode_true += test_trips['mode_confirm'].to_list()
            else:
                mode_true += list(np.full(len(test_trips), np.nan))
            if 'purpose_confirm' in test_trips.columns:
                purpose_true += list(test_trips['purpose_confirm'].to_list())
            else:
                purpose_true += np.full(len(test_trips), np.nan)
            if 'replaced_mode' in test_trips.columns:
                replaced_true += list(test_trips['replaced_mode'].to_list())
            else:
                replaced_true += list(np.full(len(test_trips), np.nan))

            mode_pred += list(next_mode_pred)
            purpose_pred += list(next_purpose_pred)
            replaced_pred += list(next_replaced_pred)

        elif data_type == 'list':
            model_ = model(user)
            train_trips = list(filter_trips[train_idx])
            test_trips = list(filter_trips[test_idx])

            idx = np.append(idx, test_idx)
            model_.fit(train_trips)

            next_mode_true, next_purpose_true, next_replaced_true = get_labels(
                test_trips)
            mode_true += next_mode_true
            purpose_true += next_purpose_true
            replaced_true += next_replaced_true

            next_mode_pred, next_purpose_pred, next_replaced_pred = model_.predict(
                test_trips)
            mode_pred += list(next_mode_pred)
            purpose_pred += list(next_purpose_pred)
            replaced_pred += list(next_replaced_pred)

    return {
        'idx': idx,
        # 'trip_idx': trip_idx,
        'mode_true': mode_true,
        'purpose_true': purpose_true,
        'replaced_true': replaced_true,
        'mode_pred': mode_pred,
        'purpose_pred': purpose_pred,
        'replaced_pred': replaced_pred,
        # 'confidence': confidence
    }


def cv_for_all_users(model,
                     uuid_list,
                     expanded_trip_df_map=None,
                     model_params=None,
                     data_type='dataframe',
                     k=5,
                     random_state=42,
                     min_samples=False,
                     raise_errors=False):
    """ runs cross_val_predict for all users in a list and returns a combined dataframe of outputs """
    assert data_type == 'dataframe' or data_type == 'list'
    dfs = []
    excluded_user_count = 0
    total_users = len(uuid_list)

    for user in uuid_list:
        # print('num trips', len(expanded_trip_df_map[user]))
        try:
            if data_type == 'dataframe':
                results = cross_val_predict(model,
                                            model_params,
                                            data_type=data_type,
                                            user_df=expanded_trip_df_map[user],
                                            k=k,
                                            random_state=random_state,
                                            min_samples=min_samples)
            elif data_type == 'list':
                results = cross_val_predict(model,
                                            model_params,
                                            data_type=data_type,
                                            user=user,
                                            k=k,
                                            random_state=random_state,
                                            min_samples=min_samples)
            if results == None:
                excluded_user_count += 1
                continue
        except Exception as e:
            if raise_errors:
                raise e
            else:
                excluded_user_count += 1
                logging.info(f'skipping user {user} due to error: {repr(e)}')
                continue

        try:
            cross_val_results = pd.DataFrame(data=results)
        except Exception as e:
            print(results)
            raise e
        cross_val_results['user_id'] = user
        cross_val_results['program'] = 'minipilot'  # TODO: fix this
        dfs += [cross_val_results]

    logging.info('using {}/{} users, excluded {}'.format(
        total_users - excluded_user_count, total_users, excluded_user_count))

    cross_val_all = pd.concat(dfs, ignore_index=True)
    cross_val_all['top_pred'] = True
    return cross_val_all


def cv_for_all_algs(uuid_list,
                    expanded_trip_df_map,
                    model_names=list(PREDICTORS.keys()),
                    override_prior_runs=True,
                    k=5,
                    random_state=42,
                    min_samples=False,
                    raise_errors=False):
    cv_results = {}
    for model_name in model_names:
        csv_path = f'cv results {model_name}.csv'
        if not override_prior_runs and os.path.exists(csv_path):
            print('loading prior cross validation data for model:', model_name)
            cv_df = pd.read_csv(csv_path,
                                keep_default_na=False,
                                na_values=[''])
            # we need to specify the parameters about na because pandas will
            # try to read the string 'n/a' as np.nan, when in fact 'n/a' is a
            # valid prediction
        else:
            print('running cross validation for model:', model_name)
            start_time = datetime.now()
            model, model_params = PREDICTORS[model_name]
            if model_name.startswith('old'):
                # we have to handle this separately because the old model was structured differently
                cv_df = cv_for_all_users(model,
                                         uuid_list=uuid_list,
                                         model_params=model_params,
                                         data_type='list',
                                         k=k,
                                         random_state=random_state,
                                         min_samples=min_samples,
                                         raise_errors=raise_errors)
            else:
                cv_df = cv_for_all_users(
                    model,
                    uuid_list=uuid_list,
                    expanded_trip_df_map=expanded_trip_df_map,
                    model_params=model_params,
                    k=k,
                    random_state=random_state,
                    min_samples=min_samples,
                    raise_errors=raise_errors)
            cv_df.to_csv(csv_path)
            end_time = datetime.now()
            print('{} time taken for {}\n'.format(end_time - start_time,
                                                  model_name))

        cv_results[model_name] = cv_df

    return cv_results


def get_clf_metrics(trip_df,
                    label_type,
                    keep_nopred=True,
                    ignore_custom=False):
    """ Args:
            trip_df: DataFrame with true labels and predicted labels. Any missing labels should be marked with np.nan
                Should have the following columns: 'mode_true', 'purpose_true', 'replaced_true', 
                'mode_pred', 'purpose_pred', 'replaced_pred', 'top_pred'
            label_type (str): 'mode', 'purpose', 'replaced', or 'tuple'
            keep_nopred (bool): whether or not to keep trips without a predicted label
            ignore_custom (bool): whether or not to remove custom labels
    """
    assert label_type in ['mode', 'purpose', 'replaced']
    assert f'{label_type}_pred' in trip_df.columns
    assert f'{label_type}_true' in trip_df.columns

    labels = np.sort(trip_df[label_type + '_true'].dropna().unique())

    # verify that the predicted labels are valid
    predicted_labels = np.sort(trip_df[label_type + '_pred'].dropna().unique())
    if label_type == 'mode' or label_type == 'purpose':
        for pl in predicted_labels:
            assert pl in labels or pl == np.nan
    elif label_type == 'replaced':
        mode_labels = np.sort(trip_df['mode_true'].dropna().unique())
        for pl in predicted_labels:
            assert pl in labels or pl in mode_labels or pl == np.nan

    # do a bunch of data filtering to keep only the desired trips

    # only keep trips that have a user input, and filter out
    # alternative predictions if there were multiple predicted labels
    labeled_predicted_df = trip_df[trip_df[label_type + '_true'].notnull() & (
        trip_df['top_pred'] | (trip_df[label_type + '_pred'].isnull()))]

    n_trips_without_prediction = len(
        labeled_predicted_df[labeled_predicted_df[label_type +
                                                  '_pred'].isnull()])

    if keep_nopred:
        labels = np.append(labels, ['no pred'])
    else:
        print(
            '{} non-predicted trips ignored out of {} total trips with user-labeled {}\n'
            .format(n_trips_without_prediction, len(labeled_predicted_df),
                    label_type))

        labeled_predicted_df = labeled_predicted_df[
            ~labeled_predicted_df[label_type + '_pred'].isnull()]

    if ignore_custom and label_type == "mode":
        print('excluded labels:',
              [l for l in labels if l not in DEFAULT_MODES])
        print()

        custom_trips = labeled_predicted_df[
            ~labeled_predicted_df[label_type + '_pred'].isin(DEFAULT_MODES)]
        print(
            '{} custom trips ignored out of {} total trips with user-labeled {}'
            .format(len(custom_trips), len(labeled_predicted_df), label_type))
        print()

        labels = [l for l in labels if l in DEFAULT_MODES]
        labeled_predicted_df = labeled_predicted_df[labeled_predicted_df[
            label_type + '_true'].isin(DEFAULT_MODES)]
        labeled_predicted_df = labeled_predicted_df[labeled_predicted_df[
            label_type + '_pred'].isin(DEFAULT_MODES)]

    elif ignore_custom and label_type == "replaced":
        print('excluded labels:',
              [l for l in labels if l not in DEFAULT_REPLACED])
        print()

        custom_trips = labeled_predicted_df[
            ~labeled_predicted_df[label_type + '_pred'].isin(DEFAULT_REPLACED)]
        print(
            '{} custom trips ignored out of {} total trips with user-labeled {}'
            .format(len(custom_trips), len(labeled_predicted_df), label_type))
        print()

        labels = [l for l in labels if l in DEFAULT_REPLACED]
        labeled_predicted_df = labeled_predicted_df[labeled_predicted_df[
            label_type + '_true'].isin(DEFAULT_REPLACED)]
        labeled_predicted_df = labeled_predicted_df[labeled_predicted_df[
            label_type + '_pred'].isin(DEFAULT_REPLACED)]

    elif ignore_custom and label_type == "purpose":
        print('excluded labels:',
              [l for l in labels if l not in DEFAULT_PURPOSES])
        print()

        custom_trips = labeled_predicted_df[
            ~labeled_predicted_df[label_type + '_pred'].isin(DEFAULT_PURPOSES)]
        print(
            '{} custom trips ignored out of {} total trips with user-labeled {}'
            .format(len(custom_trips), len(labeled_predicted_df), label_type))
        print()

        labels = [l for l in labels if l in DEFAULT_PURPOSES]
        labeled_predicted_df = labeled_predicted_df[labeled_predicted_df[
            label_type + '_true'].isin(DEFAULT_PURPOSES)]
        labeled_predicted_df = labeled_predicted_df[labeled_predicted_df[
            label_type + '_pred'].isin(DEFAULT_PURPOSES)]

    # ok now done with filtering, we can finally extract the labels
    label_true = labeled_predicted_df[label_type + '_true'].astype(str)
    label_pred = labeled_predicted_df[label_type +
                                      '_pred'].fillna('no pred').astype(str)

    # reset the labels list since the old labels list may contain labels that
    # are unused in the final label_true/label_pred array? also, it's possible
    # that label_pred contains labels not found in label_true due to the k-fold
    # splits, hence we want a union of the unique classes in label_true and
    # label_pred
    labels = np.sort(np.union1d(np.unique(label_true), np.unique(label_pred)))

    cm = sm.confusion_matrix(label_true, label_pred, labels=labels)
    mcm = sm.multilabel_confusion_matrix(label_true, label_pred, labels=labels)

    macro_f_score = sm.f1_score(label_true, label_pred, average='macro')
    weighted_f_score = sm.f1_score(label_true, label_pred, average='weighted')
    accuracy = sm.accuracy_score(label_true, label_pred)

    return {
        'labels': labels,
        'cm': cm,
        'mcm': mcm,
        'label_true': label_true,
        'label_pred': label_pred,
        'macro_f_score': macro_f_score,
        'weighted_f_score': weighted_f_score,
        'accuracy': accuracy,
        'n_trips_without_prediction': n_trips_without_prediction,
    }


def print_clf_metrics(trip_df,
                      label_type,
                      keep_nopred=True,
                      ignore_custom=False,
                      show_cm=True):
    """ prints results with nice formatting and plots the confusion matrix.
    
        label_type = 'mode', 'purpose', 'replaced'
    """
    results = get_clf_metrics(trip_df, label_type, keep_nopred, ignore_custom)
    title = 'Performance results for ' + label_type
    if keep_nopred:
        title += '\nkeep non-predicted trips'
    else:
        title += '\nexclude non-predicted trips'
    if ignore_custom:
        title += '; ignore custom labels'
    else:
        title += '; keep custom labels'

    print(title)

    print(
        sm.classification_report(results['label_true'],
                                 results['label_pred'],
                                 target_names=results['labels'],
                                 zero_division=0))

    if show_cm:

        plot_cm(results['cm'], results['labels'], title=title)


def plot_cm(cm, classes, ax=None, title='Confusion matrix'):
    """ Plots a confusion matrix with colorbar.
      
        cm: confusion matrix
        classes: list of labels
    """
    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=(10, 10))
    mappable = ax.imshow(cm, interpolation='nearest', cmap=plt.cm.Blues)
    ax.set_title(title)
    plt.colorbar(mappable, ax=ax)
    tick_marks = np.arange(len(classes))
    ax.set_xticks(np.arange(len(classes)))
    ax.set_yticks(np.arange(len(classes)))
    ax.set_xticklabels(classes, rotation=80)
    ax.set_yticklabels(classes)

    color_thresh = cm.max() / 2
    for i, j in itertools.product(range(cm.shape[0]), range(cm.shape[1])):
        ax.text(j,
                i,
                cm[i, j],
                horizontalalignment='center',
                color='white' if cm[i, j] > color_thresh else 'black')

    # plt.tight_layout()
    ax.set_ylabel('True label')
    ax.set_xlabel('Predicted label')


def plot_mcm(mcm,
             classes,
             normalize=False,
             title='Confusion matrix',
             cmap=plt.cm.Blues,
             figsize=(10, 10)):
    """ Plots the multilabel confusion matrices. 
        (Plots are pretty ugly but reformating is not a priority right now.)
    """
    fig = plt.figure(figsize=figsize)
    for i in range(len(classes)):
        cm = mcm[i]
        ax = fig.add_subplot(2, len(classes) // 2 + len(classes) % 2, i + 1)
        plot_cm(cm, ['not ' + classes[i], classes[i]], ax)

        # plt.tight_layout()


def get_cluster_metrics(expanded_all_trip_df_map, user_list, radii, loc_type,
                        algs, param_grid):
    """ Runs a bunch of clustering algorithms with varying parameters and 
        reports cluster metrics (homogeneity, modified homogeneity, purity, number of clusters, cluster sizes, etc.)

        Basically a fat gridsearch.

        Clusters contain unlabeled points but metrics are calculated using only labeled trips. 
    
        Args:
            user_list (UUID list): list of user UUIDs to test on
            radii (int list): list of radii to run the clustering algs with
            loc_type (str): 'start' or 'end'
            algs (str list): may contain 'DBSCAN', 'oursim', 'OPTICS', or 'mean_shift'
            param_grid (dict): dictionary of dictionaries. keys in the outer 
                dictionary are the alg name. keys in the inner dictionary are the param names. values in the inner dictionary are lists of parameters to test. 
                for example: 
                {
                    'DBSCAN' : {
                        'SVM': [True, False],
                        'min_samples': [2],
                    },
                    'mean_shift' : { 
                        # for mean shift, bandwidth is calculated from radius
                        'SVM': [True, False],
                        'min_samples': [2],
                        'purity_thresh': [0.8, 0.7, 0.6],
                        'size_thresh': [4, 5, 6, 7],
                        'gamma': [0.05, 0.01, 0.1],
                        'C': [1, 0.5, 2],
                    },
                    'oursim' : {},
                    'OPTICS' : {
                        'min_samples' : [2, 3, 4],
                        'xi' : [0.95, 0.9, 9.85, 0.8, 0.75],
                        'cluster_method' : ['xi'],
                    }
                }
    """
    assert loc_type == 'start' or loc_type == 'end'

    all_results = []

    try:
        for alg in algs:
            print('testing {}'.format(alg))
            if alg not in ALG_OPTIONS:
                logging.warning(f'invalid algorithm {alg}')
                continue

            alg_params = param_grid[alg]
            # print(alg_params)
            # iterate over permutation of params
            for params in iter(ParameterGrid(alg_params)):
                # print(f'params for {alg}')
                print(params)

                for user in user_list:
                    user_trips = expanded_all_trip_df_map[user]

                    if ('start_loc' not in user_trips.columns) or (
                            'end_loc' not in user_trips.columns) or (
                                'purpose_confirm' not in user_trips.columns):
                        print(f'user {user} has invalid dataframe, skipping')
                        continue

                    # expand the 'start_loc' and 'end_loc' column into
                    # 'start_lat', 'start_lon', 'end_lat', and 'end_lon' columns
                    user_trips = expand_coords(user_trips)

                    # parse parameters
                    SVM = params['SVM'] if 'SVM' in params.keys() else False
                    min_samples = params[
                        'min_samples'] if 'min_samples' in params.keys(
                        ) else None
                    xi = params['xi'] if 'xi' in params.keys() else None
                    cluster_method = params[
                        'cluster_method'] if 'cluster_method' in params.keys(
                        ) else None
                    svm_size_thresh = params[
                        'size_thresh'] if 'size_thresh' in params.keys(
                        ) else None
                    svm_purity_thresh = params[
                        'purity_thresh'] if 'purity_thresh' in params.keys(
                        ) else None
                    svm_gamma = params['gamma'] if 'gamma' in params.keys(
                    ) else None
                    svm_C = params['C'] if 'C' in params.keys() else None

                    user_trips = add_loc_clusters(
                        user_trips,
                        radii=radii,
                        alg=alg,
                        SVM=SVM,
                        loc_type=loc_type,
                        min_samples=min_samples,
                        optics_xi=xi,
                        optics_cluster_method=cluster_method,
                        svm_min_size=svm_size_thresh,
                        svm_purity_thresh=svm_purity_thresh,
                        svm_gamma=svm_gamma,
                        svm_C=svm_C)

                    metrics = []
                    for r in radii:
                        labels_true = user_trips.loc[
                            ~user_trips.purpose_confirm.isnull(),
                            'purpose_confirm']
                        labels_pred = user_trips.loc[
                            ~user_trips.purpose_confirm.isnull(),
                            f"{loc_type}_{alg}_clusters_{r}_m"]

                        # compute a bunch of metrics and save it
                        n_clusters = len(
                            user_trips[f"{loc_type}_{alg}_clusters_{r}_m"].
                            unique())
                        n_trips = len(user_trips)

                        cluster_counts = user_trips[
                            f"{loc_type}_{alg}_clusters_{r}_m"].value_counts()
                        n_single_trip_clusters = len(
                            cluster_counts.loc[cluster_counts == 1])

                        avg_cluster_size = n_trips / n_clusters
                        avg_multi_trip_cluster_size = (
                            n_trips - n_single_trip_clusters) / n_clusters

                        homogeneity = sm.homogeneity_score(
                            labels_true, labels_pred)
                        modified_homogeneity = modified_H_score(
                            labels_true, labels_pred)
                        purity = purity_score(labels_true, labels_pred)

                        metrics.append({
                            'UUID': user,
                            'alg': alg,
                            'radius': r,
                            'params': params,
                            'n_trips': n_trips,
                            'n_clusters': n_clusters,
                            'n_single_trip_clusters': n_single_trip_clusters,
                            'avg_cluster_size': avg_cluster_size,
                            'avg_multi_trip_cluster_size':
                            avg_multi_trip_cluster_size,
                            'homogeneity': homogeneity,
                            'modified_homogeneity': modified_homogeneity,
                            'purity': purity
                        })

                    metrics_by_user = pd.DataFrame.from_dict(metrics,
                                                             orient='columns')
                    all_results.append(metrics_by_user)

    except Exception as e:
        print('aborting due to Exception')
        if len(all_results) > 0:
            print('returning existing results')
            return pd.concat(all_results)
        else:
            print('no completed results to return')
            return
        print(repr(e))
    except KeyboardInterrupt as e:
        print('aborting due to KeyboardInterrupt')
        if len(all_results) > 0:
            print('returning existing results')
            return pd.concat(all_results)
        else:
            print('no completed results to return')
            return

    all_results_df = pd.concat(all_results).reset_index(drop=True)

    # plot homogeneity vs # clusters for all users in a scatterplot, one plot per radius per alg
    return all_results_df
    summary_results_df = pd.DataFrame(columns=[
        'alg', 'radius', 'params', 'n_clusters', 'avg_cluster_size',
        'avg_multi_trip_cluster_size', 'homogeneity', 'modified_homogeneity',
        'purity'
    ])

    # update summary_results


def modified_H_score(labels_true, labels_pred, t=1):
    """ Calculated the modified homogeneity score, in which t 'invisible trips'
        are introduced to penalize bins with very few trips. This should return 
        a value that is smaller than sklearn's homogeneity_score().

        See 'modified H-score exploration' notebook for more details and 
        properties.
        
        Args:
            k (int): number of 'invisible trips' to introduce
    """
    df = pd.DataFrame(
        contingency_matrix(labels_true, labels_pred, sparse=False))
    C = df.shape[0]
    N = df.sum().sum()
    entropy_C = 0
    entropy_CK = 0
    for c in range(C):
        n_c = df.iloc[c].sum()  # number of samples with label c
        if n_c == 0:
            continue
        entropy_C += (n_c / N) * (np.log(n_c) - np.log(N + t))

        for k in range(df.shape[1]):
            n_ck = df.iloc[c, k]  # number of samples in cluster k with label c
            n_k = df[df.columns[k]].sum()  # number of samples in cluster k
            if n_ck > 0:
                entropy_CK += (n_ck / N) * (np.log(n_ck) - np.log(n_k + t))
    H = 1 - (entropy_CK / entropy_C)
    return H