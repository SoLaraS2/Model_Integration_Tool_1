from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import pandas as pd
import tempfile
import os
import gc
import numpy as np

app = Flask(__name__)
CORS(app)

# Global cache for loaded files
loaded_files = {}

def get_memory_usage():
    """Optional: Monitor memory usage for debugging"""
    try:
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024  # MB
    except ImportError:
        return "psutil not available"

def optimize_dataframe_dtypes(df):
    """Optimize DataFrame memory usage by downcasting numeric types and using categories"""
    # Use category for string columns that repeat (like subsector)
    for col in df.select_dtypes(include=['object']).columns:
        if col in ['subsector', 'sector']:  # Add other categorical columns as needed
            df[col] = df[col].astype('category')
    
    # Downcast integer columns
    for col in df.select_dtypes(include=['int64']).columns:
        df[col] = pd.to_numeric(df[col], downcast='integer')
    
    # Downcast float columns
    for col in df.select_dtypes(include=['float64']).columns:
        df[col] = pd.to_numeric(df[col], downcast='float')
    
    return df

def load_scenario_file(scenario_name, year):
    """Load scenario file with aggressive chunking and memory optimization"""
    cache_key = f"{year}_{scenario_name}"
    
    if cache_key not in loaded_files:
        file_path = os.path.join("files", f"{year}_{scenario_name}.csv.gz")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        print(f"Loading {scenario_name} scenario...")
        
        # Start with chunked loading immediately to avoid memory issues
        chunks = []
        chunk_size = 10000  # Start with small chunks
        
        # Multiple fallback chunk sizes if needed
        chunk_sizes_to_try = [10000, 5000, 2000, 1000]
        
        for attempt_chunk_size in chunk_sizes_to_try:
            try:
                print(f"Attempting to load with chunk size: {attempt_chunk_size}")
                
                # Force garbage collection before attempt
                gc.collect()
                
                chunk_reader = pd.read_csv(file_path, 
                                         chunksize=attempt_chunk_size, 
                                         low_memory=True,
                                         engine='python')  # Use python engine for better memory handling
                
                chunks = []
                for i, chunk in enumerate(chunk_reader):
                    # Basic optimization on each chunk
                    # Only optimize columns that exist
                    for col in chunk.columns:
                        if chunk[col].dtype == 'object':
                            # Try to convert to category if it has repeated values
                            if col in ['subsector', 'sector'] or chunk[col].nunique() < len(chunk) * 0.5:
                                try:
                                    chunk[col] = chunk[col].astype('category')
                                except:
                                    pass
                        elif chunk[col].dtype == 'int64':
                            try:
                                chunk[col] = pd.to_numeric(chunk[col], downcast='integer')
                            except:
                                pass
                        elif chunk[col].dtype == 'float64':
                            try:
                                chunk[col] = pd.to_numeric(chunk[col], downcast='float')
                            except:
                                pass
                    
                    chunks.append(chunk)
                    
                    # More frequent garbage collection
                    if i % 5 == 0:
                        gc.collect()
                
                # Successfully loaded all chunks
                print(f"Successfully loaded {len(chunks)} chunks")
                break
                
            except Exception as e:
                print(f"Failed with chunk size {attempt_chunk_size}: {str(e)}")
                chunks = []  # Clear any partial chunks
                gc.collect()
                
                # If this was the last attempt, re-raise the error
                if attempt_chunk_size == chunk_sizes_to_try[-1]:
                    raise Exception(f"Failed to load file even with smallest chunk size: {str(e)}")
                continue
        
        # Combine chunks with memory management
        if not chunks:
            raise Exception("No chunks were successfully loaded")
        
        print(f"Combining {len(chunks)} chunks...")
        
        # Combine chunks in smaller batches to manage memory
        batch_size = max(1, len(chunks) // 10)  # Combine in batches
        combined_chunks = []
        
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            if len(batch) == 1:
                combined_chunks.append(batch[0])
            else:
                combined_batch = pd.concat(batch, ignore_index=True)
                combined_chunks.append(combined_batch)
            
            # Clear the batch from memory
            del batch
            gc.collect()
        
        # Final combination
        if len(combined_chunks) == 1:
            df = combined_chunks[0]
        else:
            df = pd.concat(combined_chunks, ignore_index=True)
        
        # Clean up
        del chunks, combined_chunks
        gc.collect()
        
        loaded_files[cache_key] = df
        print(f"Successfully loaded {scenario_name} scenario. Memory usage: {get_memory_usage()} MB")
    
    return loaded_files[cache_key]

@app.route("/process", methods=["POST"])
def process_data():
    try:
        # Clear any previous cached data and force garbage collection
        loaded_files.clear()
        gc.collect()
        
        print(f"Starting processing. Initial memory usage: {get_memory_usage()} MB")
        
        # === Step 1: Parse request ===
        data = request.json
        year = data.get("year")
        global_scenario = data.get("scenario")  # Global base scenario
        custom_values = data.get("custom_values", {})  # {key_string: percentage}
        fallback_scenarios = data.get("fallback_scenarios", {})  # {key_string: scenario}
        state_base_scenarios = data.get("state_base_scenarios", {})  # {state: scenario}

        # Subsectors that should always use baseline (no customization allowed)
        baseline_only_subsectors = {
            # Add your baseline-only subsectors here
        }

        # === Step 2: Start with global base scenario ===
        full_df = load_scenario_file(global_scenario, year).copy()
        gc.collect()  # Clean up after loading

        # === Step 3: Apply state base scenarios ===
        # Parse state base scenarios
        parsed_state_base_scenarios = {}
        for state_key, scenario in state_base_scenarios.items():
            state_key = state_key.strip().lower()
            parsed_state_base_scenarios[state_key] = scenario

        # Apply state base scenarios
        for state, state_scenario in parsed_state_base_scenarios.items():
            if state_scenario != global_scenario and state != "__all_states__":
                state_df = load_scenario_file(state_scenario, year)
                
                # Replace the entire state column with the state base scenario
                if state in full_df.columns:
                    full_df[state] = state_df[state].copy()
                
                gc.collect()  # Clean up after each operation

        # === Step 4: Apply subsector-level scenario overrides ===
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
                fallback_df = load_scenario_file(fb_scenario, year)
                fallback_subsector_df = fallback_df[fallback_df["subsector"] == subsector].copy()
                
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
                
                del fallback_subsector_df
                gc.collect()

        # === Step 5: Ensure baseline-only subsectors always use baseline ===
        if baseline_only_subsectors:
            baseline_df = load_scenario_file('baseline', year)
            for subsector in baseline_only_subsectors:
                # Remove this subsector from current data
                full_df = full_df[full_df["subsector"] != subsector]
                # Add the baseline version
                baseline_subsector_df = baseline_df[baseline_df["subsector"] == subsector].copy()
                if len(baseline_subsector_df) > 0:
                    full_df = pd.concat([full_df, baseline_subsector_df], ignore_index=True)
                del baseline_subsector_df
            gc.collect()

        # === Step 6: Apply custom percentage changes ===
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

        # === Step 7: Finalize and export ===
        print(f"Processing complete. Final memory usage: {get_memory_usage()} MB")
        
        # Create temporary file for output
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        
        # Export with optimization
        full_df.to_csv(tmp.name, index=False)
        tmp.close()
        
        # Clean up memory before returning
        del full_df
        loaded_files.clear()
        gc.collect()
        
        print(f"Export complete. Memory usage after cleanup: {get_memory_usage()} MB")
        
        return send_file(tmp.name, as_attachment=True, download_name="custom_output.csv")

    except Exception as e:
        # Clean up on error
        loaded_files.clear()
        gc.collect()
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint with memory info"""
    return jsonify({
        "status": "healthy",
        "memory_usage_mb": get_memory_usage(),
        "cached_files": len(loaded_files)
    })

if __name__ == "__main__":
    app.run(debug=True)