from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import pandas as pd
import tempfile
import os

app = Flask(__name__)
CORS(app)

@app.route("/process", methods=["POST"])
def process_data():
    try:
        # === Step 1: Parse request ===
        data = request.json
        year = data.get("year")
        global_scenario = data.get("scenario")  # Global base scenario
        custom_values = data.get("custom_values", {})  # {key_string: percentage}
        fallback_scenarios = data.get("fallback_scenarios", {})  # {key_string: scenario}
        state_base_scenarios = data.get("state_base_scenarios", {})  # {state: scenario}

        loaded_files = {}  # cache scenario files

        # === Step 2: Load scenario files ===
        def load_scenario_file(scenario_name):
            if scenario_name not in loaded_files:
                file_path = os.path.join("files", f"{year}_{scenario_name}.csv.gz")
                if not os.path.exists(file_path):
                    raise FileNotFoundError(f"File not found: {file_path}")
                df = pd.read_csv(file_path)
                loaded_files[scenario_name] = df
            return loaded_files[scenario_name]

        # Subsectors that should always use baseline (no customization allowed)
        baseline_only_subsectors = {

        }

        # === Step 3: Start with global base scenario ===
        full_df = load_scenario_file(global_scenario).copy()

        # === Step 4: Apply state base scenarios ===
        # Parse state base scenarios
        parsed_state_base_scenarios = {}
        for state_key, scenario in state_base_scenarios.items():
            state_key = state_key.strip().lower()
            parsed_state_base_scenarios[state_key] = scenario

        # Apply state base scenarios
        for state, state_scenario in parsed_state_base_scenarios.items():
            if state_scenario != global_scenario and state != "__all_states__":
                state_df = load_scenario_file(state_scenario)
                
                # Replace the entire state column with the state base scenario
                if state in full_df.columns:
                    full_df[state] = state_df[state]

        # === Step 5: Apply subsector-level scenario overrides ===
        # Parse fallback scenarios from string keys to (state, subsector) tuples
        parsed_fallback_scenarios = {}
        for key_string, fb_scenario in fallback_scenarios.items():
            try:
                parts = key_string.split(',')
                if len(parts) >= 2:
                    state = parts[0].strip().lower()
                    subsector = ','.join(parts[1:]).strip()  # Rejoin in case subsector had commas
                    parsed_fallback_scenarios[(state, subsector)] = fb_scenario
            except:
                print(f"Warning: Could not parse fallback scenario key: {key_string}")
                continue

        # Apply subsector-level scenario overrides
        for (state, subsector), fb_scenario in parsed_fallback_scenarios.items():
            # Skip baseline-only subsectors
            if subsector in baseline_only_subsectors:
                continue
                
            # Determine what scenario this subsector should be using as base
            if state in parsed_state_base_scenarios:
                current_base = parsed_state_base_scenarios[state]
            else:
                current_base = global_scenario
            
            # Only process if the fallback scenario is different from current base
            if fb_scenario != current_base:
                fallback_df = load_scenario_file(fb_scenario)
                fallback_subsector_df = fallback_df[fallback_df["subsector"] == subsector]
                
                if state == "__all_states__":
                    # Replace entire subsector across all states
                    full_df = full_df[full_df["subsector"] != subsector]
                    if len(fallback_subsector_df) > 0:
                        full_df = pd.concat([full_df, fallback_subsector_df], ignore_index=True)
                else:
                    # Replace only specific state column for this subsector
                    subsector_mask = full_df["subsector"] == subsector
                    
                    if state in full_df.columns and len(fallback_subsector_df) > 0:
                        full_df.loc[subsector_mask, state] = fallback_subsector_df[state].values

        # === Step 6: Ensure baseline-only subsectors always use baseline ===
        baseline_df = load_scenario_file('baseline')
        for subsector in baseline_only_subsectors:
            # Remove this subsector from current data
            full_df = full_df[full_df["subsector"] != subsector]
            # Add the baseline version
            baseline_subsector_df = baseline_df[baseline_df["subsector"] == subsector]
            if len(baseline_subsector_df) > 0:
                full_df = pd.concat([full_df, baseline_subsector_df], ignore_index=True)

        # === Step 7: Apply custom percentage changes ===
        # Parse custom values from string keys to (state, subsector) tuples
        parsed_custom_values = {}
        for key_string, percent in custom_values.items():
            try:
                parts = key_string.split(',')
                if len(parts) >= 2:
                    state = parts[0].strip().lower()
                    subsector = ','.join(parts[1:]).strip()  # Rejoin in case subsector had commas
                    parsed_custom_values[(state, subsector)] = percent
            except:
                print(f"Warning: Could not parse custom value key: {key_string}")
                continue

        # Apply custom percentage changes
        for (state, subsector), percent in parsed_custom_values.items():
            # Skip baseline-only subsectors
            if subsector in baseline_only_subsectors:
                continue
                
            if percent != 0.0:  # Only apply if different from 0.0 (0%)
                mask = full_df["subsector"] == subsector
                
                if state == "__all_states__":
                    # Apply to all state columns (assuming columns 4+ are states)
                    for col in full_df.columns[4:]:
                        if col not in ['weather_datetime', 'weather_year']:  # Skip non-state columns
                            full_df.loc[mask, col] *= float(percent)
                elif state in full_df.columns:
                    full_df.loc[mask, state] *= float(percent)

        # === Step 8: Finalize and export ===
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        full_df.to_csv(tmp.name, index=False)
        tmp.close()
        return send_file(tmp.name, as_attachment=True, download_name="custom_output.csv")

    except Exception as e:
        import traceback
        traceback.print_exc()  # This will help debug the error
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)