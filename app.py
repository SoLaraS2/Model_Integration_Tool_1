from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import pandas as pd
import requests
from io import StringIO
import tempfile
import os

app = Flask(__name__)
CORS(app)

@app.route("/process", methods=["POST"])
def process_data():
    data = request.json
    year = data.get("year")
    scenario = data.get("scenario")
    weather_year = data.get("weather_year")
    custom_values = data.get("custom_values", {})  # {(state, subsector): percentage}
    fallback_scenarios = data.get("fallback_scenarios", {})  # {subsector: scenario or 'baseline'}

    filename = f"{year}_{scenario}.csv.gz"
    filepath = os.path.join("files", filename)  

    try:
        df = pd.read_csv(filepath)

        if "weather_datetime" not in df.columns:
            return jsonify({"error": "'weather_datetime' column is missing in the file"}), 500

        try:
            df["weather_year"] = pd.to_datetime(df["weather_datetime"], errors='coerce').dt.year
        except Exception as e:
            return jsonify({"error": f"Failed to parse 'weather_datetime': {str(e)}"}), 500

        if df["weather_year"].isnull().all():
            return jsonify({"error": "Could not extract any valid weather years from 'weather_datetime'"}), 500

        df = df[df["weather_year"] == int(weather_year)]

        # Apply custom percentages
        for (state, subsector), percent in custom_values.items():
            mask = (df["subsector"] == subsector)
            if state == "__ALL_STATES__":
                for col in df.columns[4:]:  # apply to all states
                    df.loc[mask, col] *= float(percent)
            elif state in df.columns:
                df.loc[mask, state] *= float(percent)

        # Load fallback scenarios per subsector if needed
        for subsector, fallback_scenario in fallback_scenarios.items():
            if fallback_scenario == scenario:
                continue
            fb_filename = f"{year}_{fallback_scenario}.csv.gz"
            fb_path = os.path.join("files", fb_filename)
            fb_df = pd.read_csv(fb_path)

            if "weather_datetime" not in fb_df.columns:
                return jsonify({"error": f"'weather_datetime' column is missing in fallback file: {fb_filename}"}), 500

            try:
                fb_df["weather_datetime"] = pd.to_datetime(fb_df["weather_datetime"], errors='coerce')
                fb_df["weather_year"] = fb_df["weather_datetime"].dt.year
            except Exception as e:
                return jsonify({"error": f"Failed to parse 'weather_datetime' in fallback: {str(e)}"}), 500

            fb_df = fb_df[fb_df["weather_year"] == int(weather_year)]

            if fb_df.empty:
                return jsonify({"error": f"No fallback data for year {weather_year} in {fb_filename}"}), 404

            for state in df.columns[4:]:
                df.loc[df["subsector"] == subsector, state] = fb_df.loc[fb_df["subsector"] == subsector, state].values

        # Save and return downloadable CSV
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        df.to_csv(tmp.name, index=False)
        tmp.close()
        return send_file(tmp.name, as_attachment=True, download_name="custom_output.csv")

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
