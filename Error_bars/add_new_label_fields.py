#!/usr/bin/env python3

# This script adds the following fields to confirmed trips in Stage_analysis_timeseries:
# label_assist_labels, sensed_mode, and algorithm_chosen.

########################## IMPORTANT
# Make sure you are in an emission environment.
# Make sure that when you run this script, you are in the e-mission-server folder.
# Otherwise, e-mission-server/emission/core/get_database.py can't find conf/storage/db.conf.sample

import sys
import time

# My path looked like this: /Users/mallen2/OpenPATH_Data/e-mission-server
sys.path.insert(0, input("Enter your path to the emission server: ") ) 
import emission.storage.decorations.trip_queries as esdt
import emission.storage.timeseries.builtin_timeseries as estbt
import emission.core.wrapper.entry as ecwe

from pymongo import MongoClient
client = MongoClient()
db = client.Stage_database

# Get all confirmed trips
confirmed_trips = [doc for doc in db.Stage_analysis_timeseries.find({"metadata.key":"analysis/confirmed_trip"})]

def get_label_assist_confidences(ct):
    inference = ct['data']["inferred_labels"]
    confidences = {}
    for label_type in LABEL_CATEGORIES:
        counter = {}
        for line in inference:
            if label_type not in line["labels"]: continue  # Seems we have some incomplete tuples!
            val = line["labels"][label_type]
            if val not in counter: counter[val] = 0
            counter[val] += line["p"]

        if len(counter) > 0:
            confidences[label_type] = counter
    return confidences

def get_sensed_mode_fractions(ct):

    # These keys were found in emission/core/wrapper/modeprediction.py:
    sensed_mode_types = {0: "unknown", 1: "walking",2: "bicycling",
                     3: "bus", 4: "train", 5: "car", 6: "air_or_hsr",
                     7: "subway", 8: "tram", 9: "light_rail"}

    # Get the segments for the trip.
    #cleaned_section will only have walk/bike/automotive, inferred_section is the one that has bus/train/car etc 
    segments = esdt.get_sections_for_trip(key = "analysis/inferred_section", user_id = ct["user_id"], trip_id = ct['data']['cleaned_trip'])

    # get pairs of mode type and duration
    trip_mode_durations = {}
    total_dur = 0
    for s in segments:
        # the sensed mode is a number in the database, so I'm relabeling it as a string.
        mode = sensed_mode_types[s['data']['sensed_mode']]
        duration = s['data']['duration']

        if mode not in trip_mode_durations.keys(): trip_mode_durations[mode] = 0
        trip_mode_durations[mode] += duration

        total_dur += duration
    # convert the durations to fractions of the total segment moving time (not the trip time, since trips include stop times)
    return {mode: duration/total_dur  for mode,duration in trip_mode_durations.items()}

LABEL_CATEGORIES = ['mode_confirm','purpose_confirm','replaced_mode']
sens_count = 0
la_count = 0

# For each trip, find its segments and get consolidated label assist labels.
# update these trips in the database
print("Updating trip documents")
t1 = time.time()
for ct in confirmed_trips:

    confidences = get_label_assist_confidences(ct)
    la_mode_is_confident = 'mode_confirm' in confidences and max(list(confidences['mode_confirm'].values())) > 0.25

    # Add consolidated label assist confidences to their own field
    ct['data']['label_assist_confidences'] = confidences

    # Select an algorithm
    if 'mode_confirm' in ct['data']['user_input']:
        ct['data']['algorithm_chosen'] = 'user_input'
    elif la_mode_is_confident:
        la_count += 1
        ct['data']['algorithm_chosen'] = 'label_assist'
    else:
        sens_count += 1
        ct['data']['algorithm_chosen'] = 'sensing'

    # Add the mode:duration dictionary to the confirmed trip data as sensed_mode.
    ct["data"]["sensed_mode"] = get_sensed_mode_fractions(ct)

    # Update the corresponding confirmed_trip entry in the database.
    estbt.BuiltinTimeSeries.update(ecwe.Entry(ct))

print(f"Updated {len(confirmed_trips)} total trips in {time.time()-t1} seconds.")
print(f"There are {la_count} trips where label assist is the chosen algorithm\nand {sens_count} trips where sensing is the chosen algorithm.")