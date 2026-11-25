# Fleet Telematics and Driver Behavior Scoring

An IoT prototype that monitors a fleet, detects risky driving events, scores every trip and estimates the extra cost caused by driving behavior. Graduation project, NTI Upskilling Program, IoT track (Sara Ahmed Ragab, November 2026).

**Everything is simulated.** One vehicle runs on an ESP32 in the Wokwi simulator, and two more are simulated by a Python script. The analysis is rule-based (no machine learning).

- Wokwi project: https://wokwi.com/projects/481153186960273409
- Demo video: https://drive.google.com/file/d/1qbZSGBE6okhFAuzWlpCYA2_ZUeHoXxWX/view?usp=drivesdk
- Presentation: see `docs/`

## How it works

```
Wokwi ESP32 (V01) + Python simulator (V02, V03)
        -> MQTT broker -> Node-RED -> dashboard + live map
```

1. Each vehicle publishes JSON once per second to `PREFIX/<vehicle id>/telemetry`
   (`ts, vid, lat, lon, speed, ax, ay, temp, rpm, fuel, ign`).
2. Node-RED detects five events (harsh braking, harsh acceleration, sharp cornering, overspeed, engine overheat), groups readings into trips (ignition on to off), computes a score from 0 to 100 and an extra-cost estimate, and keeps a trip log.
3. The dashboard shows a card per vehicle (click for charts, events and last trip), a ranking and trip log with CSV export, and a live map.

## Run it

1. **Choose a unique prefix**, for example `fleet_yourname123`. The broker is public, so the prefix keeps your data separate. Use the same value in all three places: `PREFIX` in `esp32-wokwi/sketch.ino`, `--prefix` for the simulator, and the topic in the Node-RED `fleet telemetry` / `telemetry` MQTT node.
2. **Wokwi:** create an ESP32 (Arduino) project and copy `sketch.ino`, `diagram.json` and `libraries.txt` from `esp32-wokwi/`. Press Play.
3. **Node-RED:** install `node-red-dashboard` and `node-red-contrib-web-worldmap`, import `node-red/flows.json`, and deploy. The readable source of each function and template is in `node-red/src/`. Dashboard: `http://localhost:1880/ui`, map: `http://localhost:1880/worldmap`.
4. **Extra vehicles:**
   ```
   pip install paho-mqtt
   python simulator/fleet_sim.py --prefix fleet_yourname123
   ```
   Add `--vehicles "V02:reckless,V03:tired,V04:calm"` to choose profiles, or `--dry-run --minutes 120` to write a CSV dataset without MQTT.
5. Optional: to keep the trip log after restarting Node-RED, enable `contextStorage` with the `localfilesystem` module in Node-RED's `settings.js`.

## Assumptions and limits

- Speed, position and RPM of V01 are generated in firmware. Engine temperature is the MPU6050 chip temperature plus 25 C.
- V02 and V03 are synthetic driver profiles designed by the author, so their scores show that the pipeline works, not accuracy on real drivers.
- Event thresholds, score weights and most cost parameters are starting values, not field calibrated. Only the fuel price (20.5 EGP per liter diesel, October 2026) is sourced.
- A public MQTT broker without authentication or encryption is used for development only.

## Folder structure

```
esp32-wokwi/   firmware and circuit for vehicle V01
simulator/     Python vehicle simulator
node-red/      flows (add flows.json) and readable function/template source
docs/          presentation, screenshots
```
