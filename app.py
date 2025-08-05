from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import pandas as pd
import tempfile
import os
import gc
import numpy as np
import json

app = Flask(__name__)
CORS(app)

# Global cache for loaded files
loaded_files = {}

# Load shed/shift config
with open("files/shed_shift_config.json", "r") as f:
    shed_shift_config = json.load(f)

def get_memory_usage():
    try:
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024
    except ImportError:
        return "psutil not available"

def optimize_dataframe_dtypes(df):
    for col in df.select_dtypes(include=['object']).columns:
        if col in ['subsector', 'sector']:
            df[col] = df[col].astype('category')
    for col in df.select_dtypes(include=['int64']).columns:
        df[col] = pd.to_numeric(df[col], downcast='integer')
    for col in df.select_dtypes(include=['float64']).columns:
        df[col] = pd.to_numeric(df[col], downcast='float')
    return df

def load_scenario_file(scenario_name, year):
    cache_key = f"{year}_{scenario_name}"
    if cache_key not in loaded_files:
        file_path = os.path.join("files", f"{year}_{scenario_name}.csv.gz")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        df = pd.read_csv(file_path, low_memory=False)
        df = optimize_dataframe_dtypes(df)
        loaded_files[cache_key] = df
    return loaded_files[cache_key]

@app.route("/process", methods=["POST"])
def process_data():
    try:
        loaded_files.clear()
        gc.collect()
        data = request.json
        year = data.get("year")
        global_scenario = data.get("scenario")
        custom_values = data.get("custom_values", {})
        fallback_scenarios = data.get("fallback_scenarios", {})
        state_base_scenarios = data.get("state_base_scenarios", {})
        shed_shift_enabled = data.get("shed_shift_enabled", {})

        baseline_only_subsectors = {}
        full_df = load_scenario_file(global_scenario, year).copy()

        parsed_state_base_scenarios = {k.strip().lower(): v for k, v in state_base_scenarios.items()}

        for state, state_scenario in parsed_state_base_scenarios.items():
            if state_scenario != global_scenario and state != "__all_states__":
                state_col = state
                state_df = load_scenario_file(state_scenario, year)
                if state_col in full_df.columns and state_col in state_df.columns:
                    subsectors_in_df = full_df['subsector'].unique()
                    for subsector in subsectors_in_df:
                        mask_full = (full_df['subsector'] == subsector)
                        mask_state = (state_df['subsector'] == subsector)
                        # Build a mapping from weather_datetime to value for the scenario df
                        scenario_times = state_df.loc[mask_state, ['weather_datetime', state_col]]
                        scenario_map = dict(zip(scenario_times['weather_datetime'], scenario_times[state_col]))
                        # Update only where times match
                        new_values = full_df.loc[mask_full, 'weather_datetime'].map(scenario_map)
                        # Only update non-null values (where match is found)
                        update_mask = new_values.notnull()
                        full_df.loc[mask_full, state_col] = new_values.where(update_mask, full_df.loc[mask_full, state_col])


        parsed_fallback_scenarios = {}
        for key_string, fb_scenario in fallback_scenarios.items():
            parts = key_string.split(',')
            if len(parts) >= 2:
                state = parts[0].strip().lower()
                subsector = ','.join(parts[1:]).strip()
                parsed_fallback_scenarios[(state, subsector)] = fb_scenario

        for (state, subsector), fb_scenario in parsed_fallback_scenarios.items():
            if subsector in baseline_only_subsectors:
                continue
            current_base = parsed_state_base_scenarios.get(state, global_scenario)
            if fb_scenario != current_base:
                fallback_df = load_scenario_file(fb_scenario, year)
                fallback_subsector_df = fallback_df[fallback_df["subsector"] == subsector].copy()
                if state == "__all_states__":
                    full_df = full_df[full_df["subsector"] != subsector]
                    full_df = pd.concat([full_df, fallback_subsector_df], ignore_index=True)
                else:
                    subsector_mask = full_df["subsector"] == subsector
                    if state in full_df.columns:
                        full_df.loc[subsector_mask, state] = fallback_subsector_df[state].values

        baseline_df = load_scenario_file('baseline', year)
        for subsector in baseline_only_subsectors:
            full_df = full_df[full_df["subsector"] != subsector]
            baseline_subsector_df = baseline_df[baseline_df["subsector"] == subsector].copy()
            full_df = pd.concat([full_df, baseline_subsector_df], ignore_index=True)

        parsed_custom_values = {}
        for key_string, percent in custom_values.items():
            parts = key_string.split(',')
            if len(parts) >= 2:
                state = parts[0].strip().lower()
                subsector = ','.join(parts[1:]).strip()
                parsed_custom_values[(state, subsector)] = percent

        for (state, subsector), percent in parsed_custom_values.items():
            if subsector in baseline_only_subsectors:
                continue
            if percent != 0.0:
                mask = full_df["subsector"] == subsector
                if state == "__all_states__":
                    for col in full_df.columns[4:]:
                        if col not in ['weather_datetime', 'weather_year']:
                            full_df.loc[mask, col] *= float(percent)
                elif state in full_df.columns:
                    full_df.loc[mask, state] *= float(percent)

        # Add row_type column and convert datetime
        full_df["row_type"] = "original"
        full_df["weather_datetime"] = pd.to_datetime(full_df["weather_datetime"])

        # Process shed/shift functionality
        augmented_rows = []
        for state, enabled in shed_shift_enabled.items():
            if not enabled or state == "__all_states__":
                continue
            state_clean = state.strip().lower()
            if state_clean not in shed_shift_config:
                continue
            if state_clean not in full_df.columns:
                continue
            
            # Get top 250 hours across ALL subsectors for this state
            top_rows = full_df.nlargest(250, state_clean)
            #print the unique subsectors in top_rows
            unique_subsectors = top_rows['subsector'].unique()
            print("unique:", unique_subsectors,state_clean, "all done")
            
            if top_rows.empty:
                continue
            
            # Remove top rows from original full_df
            full_df = full_df.drop(top_rows.index)
            
            # Process each top row
            for _, row in top_rows.iterrows():
                subsector = row["subsector"]
                
                # Check if this subsector has shed/shift configuration
                if subsector in shed_shift_config[state_clean]:
                    vals = shed_shift_config[state_clean][subsector]
                    shed = vals.get("shed", 0.0)
                    shift = vals.get("shift", 0.0)
                    
                    # If this subsector has shed/shift percentages, split the row
                    if shed != 0.0 or shift != 0.0:
                        val = row[state_clean]
                        static_val = (1 - shed - shift) * val
                        shed_val = shed * val
                        shift_val = shift * val
                        # Defensive: never negative
                        static_val = max(static_val, 0.0)
                        shed_val = max(shed_val, 0.0)
                        shift_val = max(shift_val, 0.0)
                        
                        # Build three new rows, one for each row_type
                        for t, v in zip(['static', 'shed', 'shift'], [static_val, shed_val, shift_val]):
                            new_row = row.copy()
                            new_row[state_clean] = v
                            new_row["row_type"] = t
                            augmented_rows.append(new_row)
                    else:
                        # No shed/shift for this subsector, keep original row
                        new_row = row.copy()
                        new_row["row_type"] = "original"
                        augmented_rows.append(new_row)
                else:
                    # Subsector not in config, keep original row
                    new_row = row.copy()
                    new_row["row_type"] = "original"
                    augmented_rows.append(new_row)

        # Combine original (minus dropped) and all augmented
        if augmented_rows:
            aug_df = pd.DataFrame(augmented_rows)
            full_df = pd.concat([full_df, aug_df], ignore_index=True)

        # Save to temporary file
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        full_df.to_csv(tmp.name, index=False)
        tmp.close()
        
        # Clean up memory
        del full_df
        loaded_files.clear()
        gc.collect()
        
        return send_file(tmp.name, as_attachment=True, download_name="custom_output.csv")

    except Exception as e:
        loaded_files.clear()
        gc.collect()
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "healthy",
        "memory_usage_mb": get_memory_usage(),
        "cached_files": len(loaded_files)
    })

if __name__ == "__main__":
    app.run(debug=True)