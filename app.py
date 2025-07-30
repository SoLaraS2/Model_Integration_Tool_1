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
        scenario = data.get("scenario")
        custom_values = data.get("custom_values", {})  # {key_string: percentage}
        fallback_scenarios = data.get("fallback_scenarios", {})  # {key_string: scenario}

        loaded_files = {}  # cache scenario files

        # === Step 2: Load base data from main scenario ===
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
            'combination long-haul truck', 'motor home', 'refuse truck', 
            'school bus', 'single unit long-haul truck', 'single unit short-haul truck'
        }

        # Start with the main scenario data
        full_df = load_scenario_file(scenario)

        # Ensure baseline-only subsectors always come from baseline
        if scenario != 'baseline':
            baseline_df = load_scenario_file('baseline')
            for subsector in baseline_only_subsectors:
                # Remove this subsector from the main scenario data
                full_df = full_df[full_df["subsector"] != subsector]
                # Add the baseline version
                baseline_subsector_df = baseline_df[baseline_df["subsector"] == subsector]
                if len(baseline_subsector_df) > 0:
                    full_df = pd.concat([full_df, baseline_subsector_df], ignore_index=True)

        # === Step 3: Apply fallback scenarios ===
        # Parse fallback scenarios from string keys to (state, subsector) tuples
        parsed_fallback_scenarios = {}
        for key_string, fb_scenario in fallback_scenarios.items():
            # Parse the key string - it should be in format "state,subsector"
            try:
                # Split by comma and take only first 2 parts in case subsector has commas
                parts = key_string.split(',')
                if len(parts) >= 2:
                    state = parts[0]
                    subsector = ','.join(parts[1:])  # Rejoin in case subsector had commas
                    parsed_fallback_scenarios[(state, subsector)] = fb_scenario
            except:
                print(f"Warning: Could not parse fallback scenario key: {key_string}")
                continue

        # Apply fallback scenarios
        for (state, subsector), fb_scenario in parsed_fallback_scenarios.items():
            # Skip baseline-only subsectors - they should never be modified
            if subsector in baseline_only_subsectors:
                continue
                
            if fb_scenario != scenario:  # Only process if different from main scenario
                fallback_df = load_scenario_file(fb_scenario)
                fallback_subsector_df = fallback_df[fallback_df["subsector"] == subsector]
                
                if state == "__ALL_STATES__":
                    # Replace entire subsector
                    full_df = full_df[full_df["subsector"] != subsector]
                    full_df = pd.concat([full_df, fallback_subsector_df], ignore_index=True)
                else:
                    # Replace only specific state column for this subsector
                    subsector_mask = full_df["subsector"] == subsector
                    
                    if state in full_df.columns and len(fallback_subsector_df) > 0:
                        # Replace the specific state column data for this subsector
                        full_df.loc[subsector_mask, state] = fallback_subsector_df[state].values

        # === Step 4: Apply custom percentage changes (for ALL weather years) ===
        # Parse custom values from string keys to (state, subsector) tuples
        parsed_custom_values = {}
        for key_string, percent in custom_values.items():
            # Parse the key string - it should be in format "state,subsector"
            try:
                # Split by comma and take only first 2 parts in case subsector has commas
                parts = key_string.split(',')
                if len(parts) >= 2:
                    state = parts[0]
                    subsector = ','.join(parts[1:])  # Rejoin in case subsector had commas
                    parsed_custom_values[(state, subsector)] = percent
            except:
                print(f"Warning: Could not parse custom value key: {key_string}")
                continue

        # Apply custom percentage changes
        for (state, subsector), percent in parsed_custom_values.items():
            # Skip baseline-only subsectors - they should never be modified
            if subsector in baseline_only_subsectors:
                continue
                
            if percent != 1.0:  # Only apply if different from 1.0 (100%)
                mask = full_df["subsector"] == subsector
                
                if state == "__ALL_STATES__":
                    # Apply to all state columns (assuming columns 4+ are states)
                    for col in full_df.columns[4:]:
                        if col not in ['weather_datetime', 'weather_year']:  # Skip non-state columns
                            full_df.loc[mask, col] *= float(percent)
                elif state in full_df.columns:
                    full_df.loc[mask, state] *= float(percent)

        # === Step 5: Finalize and export ===
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