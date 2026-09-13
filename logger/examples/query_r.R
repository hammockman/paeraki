#!/usr/bin/env Rscript
# Example: Querying Paeraki telemetry database in R using DBI / RSQLite
# Install packages if needed: install.packages(c("DBI", "RSQLite", "ggplot2", "dplyr"))

suppressPackageStartupMessages({
  library(DBI)
  library(RSQLite)
})

db_path <- file.path(getwd(), "data", "paeraki.db")
if (!file.exists(db_path)) {
  # Fallback to absolute default path
  db_path <- "/home/jh/paeraki/data/paeraki.db"
}

message("Connecting to Paeraki database: ", db_path)
con <- dbConnect(RSQLite::SQLite(), dbname = db_path, flags = SQLITE_RO)

# 1. Query recent 72V telemetry
df_72v <- dbGetQuery(con, "
  SELECT 
    timestamp,
    datetime(epoch_ms / 1000, 'unixepoch') AS datetime_utc,
    total_voltage,
    current,
    power,
    rsoc,
    cell_delta_mv
  FROM telemetry_72v
  ORDER BY epoch_ms DESC
  LIMIT 500
")

message("Retrieved ", nrow(df_72v), " records from telemetry_72v")
print(head(df_72v, 10))

# 2. Compute summary statistics
if (nrow(df_72v) > 0) {
  cat("\n=== 72V Pack Summary ===\n")
  cat("Mean Voltage: ", mean(df_72v$total_voltage, na.rm = TRUE), "V\n")
  cat("Mean Power:   ", mean(df_72v$power, na.rm = TRUE), "W\n")
  cat("Mean SoC:     ", mean(df_72v$rsoc, na.rm = TRUE), "%\n")
  cat("Max Delta:    ", max(df_72v$cell_delta_mv, na.rm = TRUE), "mV\n")
}

# 3. Query 12V Solar generation
df_12v <- dbGetQuery(con, "
  SELECT 
    timestamp,
    battery_voltage,
    solar_power,
    solar_voltage,
    solar_current,
    charging_status
  FROM telemetry_12v
  ORDER BY epoch_ms DESC
  LIMIT 500
")

message("\nRetrieved ", nrow(df_12v), " records from telemetry_12v")
print(head(df_12v, 10))

dbDisconnect(con)
