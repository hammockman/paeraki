# paeraki
Ship computer

## Roadmap

1. ~~Set up VPN~~
1. Log 12V/Solar status via SRNE controller
   - systemd service
2. Log 72V status via BMS
2. Position via RTU
3. Log 230V status via smart RCBO
4. Connect to motor controller CANBUS
5. Capture SeaTalkNG data
   - compass, attitude, accelerometer, etc
   - GPS & AIS from Cortex
6. Wind instrument
7. Touchscreen display
8. Ultrasonic depth sensor
9. Auto-helm


## Design Features/Notes

- single process? single host? MQTT? RPC?
- log to file? datastore?
- visualization?
  - onboard and remote dashboards
  - local (touchscreen), android and desktop apps
- alarms
  - SMS, email