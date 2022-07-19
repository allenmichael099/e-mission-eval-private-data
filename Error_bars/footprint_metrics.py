import count_functions as counts
import pandas as pd

# Impact metric functions
def get_distances_by_mode(inferred_trips_df):
    # could modify this so we add a final mode column to the dataframe before this function is called.
    # if you want this for a given user, subset inferred_trips_df for the particular user
    distances_by_mode = {}

    for _,t in inferred_trips_df.iterrows():
        mode = counts.get_final_mode(t)
        if mode not in distances_by_mode: distances_by_mode[mode] = 0
        distances_by_mode[mode] += t["distance"]
    
    distances_by_mode["Total"] = sum(distances_by_mode.values())
    return distances_by_mode

def get_inferred_carbon_intervals(distances_by_mode, carbon_rel_errors, intensity_df):
    inferred_carbon_intervals = {}
    for mode in distances_by_mode:
        if mode == "Other": continue
        dist = distances_by_mode[mode]

        if mode == "Drove Alone":
            df_mode = "Car, drove alone"
        elif mode == "Shared Ride":
            df_mode = "Car, with others"
        elif mode == "e-bike":
            df_mode = "Pilot ebike"
        elif mode == "Bike":
            df_mode = "Regular Bike"
        else:
            df_mode = mode

        lower_rel_error = carbon_rel_errors[mode][0] # this is negative
        upper_rel_error = carbon_rel_errors[mode][1]
        
        carbon_intensity = pd.Series.to_numpy(intensity_df[intensity_df["mode"] == df_mode]["CO2_factor"])  # CO2_factor units: lb_CO2/MMBTU

        if len(carbon_intensity) > 0:
            carbon_estimate = dist*carbon_intensity[0]
            carbon_interval = [carbon_estimate*(1 + lower_rel_error), carbon_estimate*(1+upper_rel_error)]
            inferred_carbon_intervals[mode]= {"estimate": carbon_estimate, "interval": carbon_interval}
        else: continue
    return inferred_carbon_intervals

def get_inferred_energy_intervals(distances_by_mode, energy_rel_errors, intensity_df):
    inferred_energy_intervals = {}
    for mode in distances_by_mode:
        if mode == "Other": continue
        dist = distances_by_mode[mode]

        if mode == "Drove Alone":
            df_mode = "Car, drove alone"
        elif mode == "Shared Ride":
            df_mode = "Car, with others"
        elif mode == "e-bike":
            df_mode = "Pilot ebike"
        elif mode == "Bike":
            df_mode = "Regular Bike"
        elif mode == "Other":
            df_mode = "Not a trip"
        else:
            df_mode = mode

        lower_rel_error = energy_rel_errors[mode][0]  # this is negative
        upper_rel_error = energy_rel_errors[mode][1]
        
        energy_intensity = pd.Series.to_numpy(intensity_df[intensity_df["mode"] == df_mode]["energy_intensity_factor"])   # energy intensity units: BTU/PMT

        if len(energy_intensity) > 0:
            energy_estimate = dist*energy_intensity[0]
            energy_interval = [energy_estimate*(1 + lower_rel_error), energy_estimate*(1+upper_rel_error)]
            inferred_energy_intervals[mode]= {"estimate": energy_estimate, "interval": energy_interval}
        else: continue
    return inferred_energy_intervals