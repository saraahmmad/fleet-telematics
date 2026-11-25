#!/usr/bin/env python3
"""
Fleet Telematics - Step 2
Simulates extra vehicles (different driver profiles) and publishes them to the
SAME MQTT topics / JSON format as the ESP32 in Wokwi:

    PREFIX/<vid>/telemetry   -> JSON every second
    PREFIX/<vid>/status      -> online / offline (retained, with Last Will)

Live mode  : python fleet_sim.py --prefix fleet_sara7392
Dataset    : python fleet_sim.py --dry-run --minutes 120      (no MQTT, fast, writes CSV)
"""
import argparse
import csv
import json
import math
import random
import time

# ---------------------------------------------------------------------------
# Driver profiles (starting values: tune them and justify them in the report)
#   acc / brk      : max speed change per second (km/h per s)   3.5 ~= 0.10 g
#   panic_brk      : speed drop per second during a sudden stop
#   panic_p        : probability per second of starting a sudden stop (speed>25)
#   cruise         : target speed range (km/h)
#   seg            : how long a speed target is kept (seconds)
#   turn_p/turn_g  : probability per second / size (g) of a lateral event
#   weave          : slow side-to-side drift amplitude (g)
#   temp           : engine temperature range reached during a trip (C)
#   idle           : seconds standing still with ignition ON at trip start
# ---------------------------------------------------------------------------
PROFILES = {
    "calm": dict(acc=3.5, brk=4.5, panic_brk=0, panic_p=0.0,
                 cruise=(30, 46), seg=(15, 30), turn_p=0.03, turn_g=(0.08, 0.18),
                 weave=0.0, noise=0.02, temp=(86, 94), idle=(3, 6), fuel_k=1.0),
    "reckless": dict(acc=13.0, brk=15.0, panic_brk=15.0, panic_p=0.008,
                     cruise=(58, 80), seg=(15, 30), turn_p=0.04, turn_g=(0.35, 0.60),
                     weave=0.0, noise=0.04, temp=(98, 112), idle=(1, 3), fuel_k=1.5),
    "tired": dict(acc=5.0, brk=7.0, panic_brk=13.0, panic_p=0.015,
                  cruise=(35, 55), seg=(10, 25), turn_p=0.08, turn_g=(0.20, 0.40),
                  weave=0.12, noise=0.05, temp=(90, 100), idle=(20, 40), fuel_k=1.2),
}

G = 9.81


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


class Vehicle:
    def __init__(self, vid, profile, lat, lon, rng, trip_s=150):
        self.vid, self.profile, self.p = vid, profile, PROFILES[profile]
        self.rng = rng
        self.lat, self.lon = lat, lon
        self.heading = rng.uniform(0, 360)
        self.trip_s = trip_s
        self.fuel = rng.uniform(60, 95)
        self.temp = 40.0
        self.temp_target = 90.0
        self.speed = 0.0
        self.state, self.timer = "off", rng.randint(2, 8)
        self.trip_left = 0
        self.seg_left = 0
        self.target = 0.0
        self.panic = 0
        self.turn = 0
        self.turn_val = 0.0
        self.t = 0

    # -- one simulated second ------------------------------------------------
    def step(self, ts):
        rng, p = self.rng, self.p
        self.t += 1
        ax = ay = 0.0

        if self.state == "off":
            self.speed = 0.0
            self.temp = max(40.0, self.temp - 0.5)
            self.timer -= 1
            if self.timer <= 0:
                self.state, self.timer = "idle", rng.randint(*p["idle"])
                self.temp_target = rng.uniform(*p["temp"])
        elif self.state == "idle":
            self.speed = 0.0
            self.temp += clamp(self.temp_target - self.temp, -1, 1)
            self.fuel -= 0.002
            self.timer -= 1
            if self.timer <= 0:
                self.state, self.trip_left = "drive", self.trip_s
                self.seg_left = 0
        else:  # drive
            self.trip_left -= 1
            old = self.speed
            if self.trip_left <= 12:
                self.target = 0.0
            elif self.seg_left <= 0:
                self.seg_left = rng.randint(*p["seg"])
                if rng.random() < 0.15:
                    self.target = rng.uniform(0, 15)
                else:
                    self.target = rng.uniform(*p["cruise"])
            self.seg_left -= 1

            if self.panic > 0:
                dv = -p["panic_brk"]
                self.panic -= 1
            else:
                if p["panic_p"] and self.speed > 25 and self.trip_left > 15 \
                        and rng.random() < p["panic_p"]:
                    self.panic = rng.randint(2, 3)
                dv = clamp(self.target - self.speed, -p["brk"], p["acc"])
            self.speed = max(0.0, self.speed + dv)
            ax = (self.speed - old) / 3.6 / G + rng.gauss(0, p["noise"])

            # lateral acceleration
            if self.turn > 0:
                ay = self.turn_val
                self.turn -= 1
            elif self.speed > 10 and rng.random() < p["turn_p"]:
                lo, hi = p["turn_g"]
                self.turn_val = rng.choice([-1, 1]) * rng.uniform(lo, hi)
                self.turn = rng.randint(1, 3)
                ay = self.turn_val
            else:
                ay = rng.gauss(0, p["noise"])
            ay += p["weave"] * math.sin(self.t / 4.0)

            # movement
            self.heading = (self.heading + ay * 10 + rng.gauss(0, 0.5)) % 360
            dist = self.speed / 3.6
            h = math.radians(self.heading)
            self.lat += dist * math.cos(h) / 111320.0
            self.lon += dist * math.sin(h) / (111320.0 * math.cos(math.radians(self.lat)))
            self.fuel -= (dist / 1000.0) * 0.6 * p["fuel_k"]
            self.temp += clamp(self.temp_target - self.temp, -1, 1)

            if self.trip_left <= 0 and self.speed == 0:
                self.state, self.timer = "off", rng.randint(5, 10)

        if self.fuel < 15:
            self.fuel = 95.0
        ign = 1 if self.state in ("idle", "drive") else 0
        rpm = int(800 + self.speed * 30) if ign else 0
        return {
            "ts": ts, "vid": self.vid,
            "lat": round(self.lat, 6), "lon": round(self.lon, 6),
            "speed": round(self.speed, 1),
            "ax": round(ax, 3), "ay": round(ay, 3),
            "temp": round(self.temp + rng.gauss(0, 0.3), 1),
            "rpm": rpm, "fuel": round(self.fuel, 1), "ign": ign,
        }


def make_client(client_id, will_topic):
    import paho.mqtt.client as mqtt
    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except AttributeError:          # paho-mqtt 1.x
        c = mqtt.Client(client_id=client_id)
    c.will_set(will_topic, "offline", qos=1, retain=True)
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="fleet_CHANGE_ME_123")
    ap.add_argument("--host", default="broker.hivemq.com")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--vehicles", default="V02:reckless,V03:tired",
                    help="comma list of ID:profile (profiles: calm, reckless, tired)")
    ap.add_argument("--trip-seconds", type=int, default=150)
    ap.add_argument("--dry-run", action="store_true",
                    help="no MQTT: generate a dataset quickly and write a CSV")
    ap.add_argument("--minutes", type=int, default=60, help="dry-run length (simulated)")
    ap.add_argument("--csv", default=None, help="CSV path ('' to disable)")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    base_lat, base_lon = 30.0444, 31.2357       # same start area as the ESP32 code
    fleet = []
    for i, item in enumerate(args.vehicles.split(",")):
        vid, prof = item.strip().split(":")
        if prof not in PROFILES:
            raise SystemExit(f"unknown profile '{prof}' (use: {', '.join(PROFILES)})")
        fleet.append(Vehicle(vid, prof,
                             base_lat + 0.002 * (i + 1), base_lon + 0.002 * (i + 1),
                             random.Random(rng.random()), args.trip_seconds))

    csv_path = args.csv
    if csv_path is None:
        csv_path = "fleet_dataset.csv" if args.dry_run else "fleet_log.csv"
    fcsv = writer = None
    if csv_path:
        fcsv = open(csv_path, "w", newline="")
        writer = csv.writer(fcsv)
        writer.writerow(["ts", "vid", "profile", "lat", "lon", "speed", "ax", "ay",
                         "temp", "rpm", "fuel", "ign"])

    def log(v, d):
        if writer:
            writer.writerow([d["ts"], d["vid"], v.profile, d["lat"], d["lon"], d["speed"],
                             d["ax"], d["ay"], d["temp"], d["rpm"], d["fuel"], d["ign"]])

    if args.dry_run:
        ts = int(time.time())
        for sec in range(args.minutes * 60):
            for v in fleet:
                log(v, v.step(ts + sec))
        if fcsv:
            fcsv.close()
        print(f"dataset written to {csv_path}: {args.minutes} min x {len(fleet)} vehicles")
        return

    # ---- live mode ---------------------------------------------------------
    clients = {}
    for v in fleet:
        st = f"{args.prefix}/{v.vid}/status"
        c = make_client(f"{args.prefix}-{v.vid}-sim-{rng.randint(0, 65535):04X}", st)
        c.connect(args.host, args.port, 30)
        c.loop_start()
        c.publish(st, "online", qos=1, retain=True)
        clients[v.vid] = c
        print(f"{v.vid} ({v.profile}) connected -> {args.prefix}/{v.vid}/telemetry")

    print("Publishing every second. Press Ctrl+C to stop.")
    nxt = time.time()
    try:
        while True:
            ts = int(time.time())
            for v in fleet:
                d = v.step(ts)
                clients[v.vid].publish(f"{args.prefix}/{v.vid}/telemetry", json.dumps(d))
                log(v, d)
            if fcsv:
                fcsv.flush()
            nxt += 1.0
            time.sleep(max(0.0, nxt - time.time()))
    except KeyboardInterrupt:
        print("stopping...")
    finally:
        for vid, c in clients.items():
            c.publish(f"{args.prefix}/{vid}/status", "offline", qos=1, retain=True)
            time.sleep(0.2)
            c.loop_stop()
            c.disconnect()
        if fcsv:
            fcsv.close()


if __name__ == "__main__":
    main()
