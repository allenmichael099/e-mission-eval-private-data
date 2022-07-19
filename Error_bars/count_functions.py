# Final mode functions
def sensed_mode(mode):
        if mode == "unknown":
            return "Other"
        elif mode == "walking": 
            return "Walk"
        elif mode == "bicycling":
            return "Bike"
        elif mode ==  "bus": 
            return "Bus"
        elif mode == "train":
            return "Train"
        elif mode ==  "car": 
            return "Drove Alone"
        elif mode ==  "air_or_hsr":
            return "air"
        elif mode == "subway": 
            return "Train"
        elif mode == "tram": 
            return "Train"
        elif mode == "light_rail":
            return "Train"
        else:
            Warning("Sensed mode had a different label than expected")

        '''sensed_mode_types = {0: "unknown", 1: "walking",2: "bicycling",
                     3: "bus", 4: "train", 5: "car", 6: "air_or_hsr",
                     7: "subway", 8: "tram", 9: "light_rail"}'''

        '''UNKNOWN = 0 Other
        WALKING = 1  Walk
        BICYCLING = 2 Bike
        BUS = 3       Bus 
        TRAIN = 4     Train
        CAR = 5       Drove Alone
        AIR_OR_HSR = 6 Air
        SUBWAY = 7     Train
        TRAM = 8        Train
        LIGHT_RAIL = 9  Train'''

def get_final_mode(trip):
    if  trip["algorithm_chosen"] == "sensing" and len(trip["sensed_mode"] > 0):
        sensed_label = max(trip["sensed_mode"], key=trip["sensed_mode"].get)
        final_mode = sensed_mode(sensed_label)
    else:  # how do we handle if there is no sensed and no inferred mode?
        label_category_labels = trip["label_assist_confidences"]["mode_confirm"]
        final_label_category_label = max(label_category_labels, key=label_category_labels.get)

        if final_label_category_label not in accepted_labels["mode_confirm"]:
            final_mode = "Other"
        else:
            final_mode = final_label_category_label

    return final_mode

def get_inferred_counts(inferred_trips):    
    ''' Counts the number of times a given label value is inferred.
    Returns a dictionary by label type of a dictionary by label value of the number of inferred trips for each label value.
    eg {"mode_confirm": {bike: 1, car: 2, etc}, "purpose_confirm: {"shopping": 2, "Home": 3}, "replaced_mode": {"No travel": 5, "Car, drove alone": 2} '''

    all_inferred_counts = {} 

    # for each label type, get the counts for each of the possible label values
    for label_type in LABEL_CATEGORIES:
        all_inferred_counts[label_type] = {}

        for _,t in inferred_trips.iterrows():
            if label_type == "mode_confirm":
                final_label = get_final_mode(t)
            else:
                # make sure the category exists!
                if label_type in t["label_assist_confidences"]:
                    label_category_labels = t["label_assist_confidences"][label_type]
                    final_label = max(label_category_labels, key=label_category_labels.get)
                else:
                    continue

            if final_label not in all_inferred_counts[label_type]: all_inferred_counts[label_type][final_label] = 0
            all_inferred_counts[label_type][final_label] += 1

    return all_inferred_counts

def get_count_intervals(all_inferred_counts, label_categories, rel_count_errors):
    '''Get interval estimates based on the count values. Currently only for mode_confirm.
    eg {"mode_confirm": {"Bike": {"count": 2, "interval": [0,3]}, "Drove Alone": {"count": ...}'''

    count_intervals = {}

    for label_type in label_categories:
        if label_type != "mode_confirm": continue
        count_intervals[label_type] = {} 

        rel_errors = rel_count_errors[label_type]
        #print(rel_errors)
        # Get the intervals for the standard labels.
        for final_label in all_inferred_counts[label_type]:
            count_intervals[label_type][final_label] = {}

            count = all_inferred_counts[label_type][final_label]
            lower_rel_error = rel_errors[final_label][0]  # this is negative
            upper_rel_error = rel_errors[final_label][1]
            interval = [count*(1 + lower_rel_error), count*(1+upper_rel_error)]

            count_intervals[label_type][final_label] = {"count": count, "interval": interval}
    return count_intervals