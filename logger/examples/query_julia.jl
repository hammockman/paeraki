#!/usr/bin/env julia
# Example: Querying Paeraki telemetry database in Julia
# Install packages if needed: using Pkg; Pkg.add(["SQLite", "DataFrames"])

using SQLite
using DataFrames

db_path = isfile("data/paeraki.db") ? "data/paeraki.db" : "/home/jh/paeraki/data/paeraki.db"

println("Connecting to Paeraki database: ", db_path)
db = SQLite.DB(db_path)

# Query recent 72V telemetry
query_72v = """
    SELECT 
        timestamp,
        total_voltage,
        current,
        power,
        rsoc,
        cell_delta_mv
    FROM telemetry_72v
    ORDER BY epoch_ms DESC
    LIMIT 20
"""

df_72v = DBInterface.execute(db, query_72v) |> DataFrame
println("\n=== Recent 72V Propulsion Telemetry ===")
println(first(df_72v, 10))

# Query recent 12V telemetry
query_12v = """
    SELECT 
        timestamp,
        battery_voltage,
        solar_power,
        solar_voltage,
        solar_current,
        charging_status
    FROM telemetry_12v
    ORDER BY epoch_ms DESC
    LIMIT 20
"""

df_12v = DBInterface.execute(db, query_12v) |> DataFrame
println("\n=== Recent 12V House/Solar Telemetry ===")
println(first(df_12v, 10))

# Query recent SeaTalkNG telemetry
query_stng = """
    SELECT 
        timestamp,
        heading_deg,
        heading_ref,
        pitch_deg,
        roll_deg,
        latitude,
        longitude,
        sog_knots,
        satellites,
        pilot_mode
    FROM telemetry_seatalkng
    ORDER BY epoch_ms DESC
    LIMIT 20
"""

df_stng = DBInterface.execute(db, query_stng) |> DataFrame
println("\n=== Recent SeaTalkNG Vessel Telemetry ===")
println(first(df_stng, 10))

# Query recent AIS targets
query_ais = """
    SELECT 
        timestamp,
        mmsi,
        vessel_name,
        ais_class,
        range_nm,
        bearing_deg,
        sog_knots,
        nav_status
    FROM telemetry_ais
    ORDER BY epoch_ms DESC
    LIMIT 20
"""

df_ais = DBInterface.execute(db, query_ais) |> DataFrame
println("\n=== Recent AIS Targets in Range ===")
println(first(df_ais, 10))
