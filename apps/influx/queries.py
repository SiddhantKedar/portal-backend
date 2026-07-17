# apps/influx/queries.py
# All InfluxDB Flux queries live here.
# Views call these functions — no Flux anywhere else in the codebase.
# Each function returns clean Python dicts, no InfluxDB objects leak out.

from datetime import datetime, timezone, timedelta
from .client import get_influx_client
import os
import re

INFLUX_ORG = os.getenv('INFLUX_ORG')

# CEA (Central Electricity Authority) all-India weighted average grid
# emission factor, FY 2024-25, CO2 Baseline Database User Guide V21.0
# (Nov 2025). Update when CEA publishes a new edition.
CO2_AVOIDED_FACTOR_KG_PER_KWH = 0.71

MIN_POA_KWH_M2_FOR_PR = 0.1

# Determine when to show device is offline
STALE_AFTER_SECONDS = 120


# ── Timezone Helper ────────────────────────────────────────────────────────────

def get_ist_midnight_utc():
    """
    Returns today's IST midnight as a UTC datetime string for Flux range().
    IST = UTC+5:30, so IST midnight = UTC previous day 18:30.
    eg: IST 2026-06-03 00:00 = UTC 2026-06-02 18:30
    """
    ist          = timezone(timedelta(hours=5, minutes=30))
    now_ist      = datetime.now(ist)
    midnight_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc = midnight_ist.astimezone(timezone.utc)
    return midnight_utc.strftime('%Y-%m-%dT%H:%M:%SZ')


def get_n_days_ago_midnight_utc(n):
    """
    Returns IST midnight n days ago as UTC string.
    Used for the 7-day daily energy query.
    """
    ist          = timezone(timedelta(hours=5, minutes=30))
    now_ist      = datetime.now(ist)
    past_ist     = now_ist - timedelta(days=n)
    midnight_ist = past_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc = midnight_ist.astimezone(timezone.utc)
    return midnight_utc.strftime('%Y-%m-%dT%H:%M:%SZ')


# Helper for checking if data is live :
def _is_fresh(record_time):
    """True if a record's timestamp is within the staleness threshold."""
    if record_time is None:
        return False
    age = (datetime.now(timezone.utc) - record_time).total_seconds()
    return age <= STALE_AFTER_SECONDS


# ── Overview Queries ───────────────────────────────────────────────────────────

def _query_inverter_snapshot(query_api, bucket, site_id, inverter_ids):
    """
    Internal: fetches latest values for all inverters.
    Returns { 'inverter1': { 'ac_active_power_kw': 35.0, ... }, ... }
    """
    device_filter = ' or '.join(
        [f'r.device == "{d}"' for d in inverter_ids]
    )

    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: -10m)
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => {device_filter})
            |> filter(fn: (r) =>
                r._field == "ac_active_power_kw" or
                r._field == "energy_daily_kwh"    or
                r._field == "grid_frequency_hz"         or
                r._field == "ac_power_factor"           or
                r._field == "internal_temp_c" or
                r._field == "inverter_efficiency_pct"   or
                r._field == "ac_reactive_power_kvar"
            )
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> last()
    '''

    tables      = query_api.query(flux, org=INFLUX_ORG)
    device_data = {}
    device_times = {}

    for table in tables:
        for record in table.records:
            time = record.get_time()
            if not _is_fresh(time):
                continue

            device = record.values.get('device')
            field  = record.get_field()
            value  = record.get_value()

            if device not in device_data:
                device_data[device] = {}
            device_data[device][field] = value

            if device not in device_times or time > device_times[device]:
                device_times[device] = time

    return device_data, device_times


def _query_meter_snapshot(query_api, bucket, site_id, meter_id):
    """
    Internal: fetches latest values from the plant meter.
    Returns { 'current_phase_a': 3.14, 'voltage_line_ab_v': 10.9, ... }
    """
    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: -10m)
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{meter_id}")
            |> filter(fn: (r) =>
                r._field == "current_phase_a"        or
                r._field == "current_phase_b"        or
                r._field == "current_phase_c"        or
                r._field == "voltage_line_ab_v"      or
                r._field == "voltage_line_bc_v"      or
                r._field == "voltage_line_ca_v"      or
                r._field == "reactive_power_total_kvar"
            )
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> last()
    '''

    tables      = query_api.query(flux, org=INFLUX_ORG)
    meter_data  = {}

    for table in tables:
        for record in table.records:
            if not _is_fresh(record.get_time()):
                continue
            meter_data[record.get_field()] = record.get_value()

    return meter_data


def _query_power_trend(query_api, bucket, site_id, inverter_ids, interval_minutes):
    """
    Internal: fetches today's power trend aggregated by interval.
    Returns [ { 'time': '...', 'total_kw': 104.0 }, ... ]
    """
    device_filter = ' or '.join(
        [f'r.device == "{d}"' for d in inverter_ids]
    )
    start = get_ist_midnight_utc()

    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: {start})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => {device_filter})
            |> filter(fn: (r) => r._field == "ac_active_power_kw")
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> aggregateWindow(every: {interval_minutes}m, fn: mean, createEmpty: false)
            |> pivot(rowKey: ["_time"], columnKey: ["device"], valueColumn: "_value")
    '''

    tables  = query_api.query(flux, org=INFLUX_ORG)
    results = []

    for table in tables:
        for record in table.records:
            total = sum(
                record.values.get(d) or 0.0
                for d in inverter_ids
            )
            results.append({
                'time':     record.get_time().isoformat(),
                'total_kw': round(total, 2),
            })

    results.sort(key=lambda x: x['time'])
    return results


def _query_breaker_live(query_api, bucket, site_id, device_id):
    """
    Main breaker + service status via Grafana-parity logic.

    Fetches dido_01 (breaker on), dido_03 (breaker trip), and dido_05
    (in service) in one pivoted query, then decodes each signal on the
    record's OWN timestamp — a point older than STALE_AFTER_SECONDS is
    treated as offline, exactly like Grafana's date.sub(now(), 15m) check.

    Two independent signals, surfaced as two fields:
        breaker_status : 'on' | 'trip' | 'off' | 'offline' | None
        service_status : 'in_service' | 'out_of_service' | 'offline' | None

    Precedence on breaker_status matches Grafana: trip wins over on.

    Returns {} only if no data at all in the window (device never seen).
    """
    flux = f'''
        import "date"

        from(bucket: "{bucket}")
            |> range(start: -15m)
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{device_id}")
            |> filter(fn: (r) =>
                r._field == "dido_01" or
                r._field == "dido_03" or
                r._field == "dido_05"
            )
            |> last()
            |> pivot(rowKey: ["device", "_time"], columnKey: ["_field"], valueColumn: "_value")
            |> map(fn: (r) => ({{
                _time: r._time,
                breaker_code:
                  if r._time < date.sub(from: now(), d: {STALE_AFTER_SECONDS}s) then 3
                  else if exists r.dido_03 and int(v: r.dido_03) == 1 then 2
                  else if exists r.dido_01 and int(v: r.dido_01) == 1 then 1
                  else 0,
                service_code:
                  if r._time < date.sub(from: now(), d: {STALE_AFTER_SECONDS}s) then 6
                  else if exists r.dido_05 and int(v: r.dido_05) == 1 then 5
                  else 4,
            }}))
    '''

    tables = query_api.query(flux, org=INFLUX_ORG)

    breaker_code = None
    service_code = None
    for table in tables:
        for record in table.records:
            breaker_code = int(record.values.get('breaker_code'))
            service_code = int(record.values.get('service_code'))

    if breaker_code is None:
        return {}

    breaker_map = {0: 'off', 1: 'on', 2: 'trip', 3: 'offline'}
    service_map = {4: 'out_of_service', 5: 'in_service', 6: 'offline'}

    return {
        'breaker_status': breaker_map.get(breaker_code),
        'service_status': service_map.get(service_code),
    }


def get_dashboard_overview(bucket, site_id, inverter_ids, meter_id, interval_minutes=5):
    """
    Main dashboard overview — single function, three internal queries.
    Returns everything the plant overview page needs in one call.

    Args:
        bucket           : InfluxDB bucket (from Customer.influx_bucket)
        site_id          : site tag (from Site.influx_site_id)
        inverter_ids     : list of inverter device tags
        meter_id         : plant meter device tag
        interval_minutes : power trend aggregation window

    Returns a single dict with plant, grid, inverters and power_trend.
    """
    client    = get_influx_client()
    query_api = client.query_api()

    try:
        # Fire all three queries
        inverter_data, inverter_times = _query_inverter_snapshot(
            query_api, bucket, site_id, inverter_ids
        )
        meter_data = _query_meter_snapshot(
            query_api, bucket, site_id, meter_id
        )
        power_trend = _query_power_trend(
            query_api, bucket, site_id, inverter_ids, interval_minutes
        )

        client.close()

        # ── Aggregate inverter values ──────────────────────────────────────────
        total_active_power  = 0.0
        total_daily_gen     = 0.0
        grid_freq           = None
        power_factor        = None
        last_updated        = None

        inverter_list = []

        for device_id in inverter_ids:
            fields = inverter_data.get(device_id, {})
            t      = inverter_times.get(device_id)

            total_active_power += fields.get('ac_active_power_kw', 0.0)
            total_daily_gen    += fields.get('energy_daily_kwh', 0.0)

            if grid_freq is None:
                grid_freq    = fields.get('grid_frequency_hz')
            if power_factor is None:
                power_factor = fields.get('ac_power_factor')
            if last_updated is None or (t and t > last_updated):
                last_updated = t

            inverter_list.append({
                'device_id':       device_id,
                'active_power_kw': round(fields.get('ac_active_power_kw', 0.0), 2),
                'daily_gen_kwh':   round(fields.get('energy_daily_kwh', 0.0), 3),
                'internal_temp_c':    round(fields.get('internal_temp_c', 0.0), 1),
                'inverter_efficiency_pct':      round(fields.get('inverter_efficiency_pct', 0.0), 1),
                'status':          'online' if fields else 'offline',
                'last_updated':    t.isoformat() if t else None,
            })

        # ── Assemble final response ────────────────────────────────────────────
        return {
            'last_updated': last_updated.isoformat() if last_updated else None,

            'plant': {
                'active_power_kw':    round(total_active_power, 2),
                'reactive_power_kvar': round(meter_data.get('reactive_power_total_kvar', 0.0), 2),
                'energy_today_kwh':   round(total_daily_gen, 3),
                'frequency_hz':       round(grid_freq, 2) if grid_freq else None,
                'power_factor':       round(power_factor, 2) if power_factor else None,
            },

            'grid': {
                'current_a':    round(meter_data.get('current_phase_a', 0.0), 2),
                'current_b':    round(meter_data.get('current_phase_b', 0.0), 2),
                'current_c':    round(meter_data.get('current_phase_c', 0.0), 2),
                'voltage_ab':   round(meter_data.get('voltage_line_ab_v', 0.0), 3),
                'voltage_bc':   round(meter_data.get('voltage_line_bc_v', 0.0), 3),
                'voltage_ca':   round(meter_data.get('voltage_line_ca_v', 0.0), 3),
            },

            'inverters':    inverter_list,
            'power_trend':  power_trend,
        }

    except Exception as e:
        client.close()
        raise Exception(f'Dashboard overview query failed: {str(e)}')


# ── Daily Energy (Separate Endpoint) ──────────────────────────────────────────

def get_daily_energy(bucket, site_id, meter_id, days=7):
    """
    Returns daily generation for the last N days.
    Uses meter1 energy_active_export_kwh — calculates last - first per day.
    Matches exactly the Grafana query logic.
    IST timezone aware.

    Returns:
    [
        { 'date': '2026-05-31', 'energy_kwh': 6250.0 },
        { 'date': '2026-06-01', 'energy_kwh': 6290.0 },
        ...
    ]
    """
    client    = get_influx_client()
    query_api = client.query_api()

    start = get_n_days_ago_midnight_utc(days - 1)
    ist_offset = '5h30m'

    # Matches the Grafana query exactly:
    # daily = last(energy_export) - first(energy_export) per day
    flux = f'''
        import "date"
        import "timezone"

        option location = timezone.fixed(offset: {ist_offset})

        day_first = from(bucket: "{bucket}")
            |> range(start: {start})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{meter_id}")
            |> filter(fn: (r) => r._field == "energy_active_export_kwh")
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> aggregateWindow(every: 1d, fn: first, createEmpty: false, timeSrc: "_start")
            |> map(fn: (r) => ({{r with _field: "v_first"}}))

        day_last = from(bucket: "{bucket}")
            |> range(start: {start})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{meter_id}")
            |> filter(fn: (r) => r._field == "energy_active_export_kwh")
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> aggregateWindow(every: 1d, fn: last, createEmpty: false, timeSrc: "_start")
            |> map(fn: (r) => ({{r with _field: "v_last"}}))

        union(tables: [day_first, day_last])
            |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
            |> map(fn: (r) => ({{
                _time  : r._time,
                _value : r.v_last - r.v_first,
                _field : "daily_generation_kwh"
            }}))
            |> keep(columns: ["_time", "_value", "_field"])
    '''

    try:
        tables  = query_api.query(flux, org=INFLUX_ORG)
        client.close()

        results = []
        for table in tables:
            for record in table.records:
                # Convert UTC time to IST date for display
                utc_time  = record.get_time()
                ist_tz    = timezone(timedelta(hours=5, minutes=30))
                ist_time  = utc_time.astimezone(ist_tz)

                results.append({
                    'date':       ist_time.strftime('%Y-%m-%d'),
                    'energy_kwh': round(record.get_value(), 2),
                })

        results.sort(key=lambda x: x['date'])
        return results

    except Exception as e:
        client.close()
        raise Exception(f'Daily energy query failed: {str(e)}')


# ── System Health (unchanged from before) ─────────────────────────────────────

def get_system_health(bucket, site_id, device_id, range_hours=3):
    client    = get_influx_client()
    query_api = client.query_api()

    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: -{range_hours}h)
            |> filter(fn: (r) => r._measurement == "system_health")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{device_id}")
            |> filter(fn: (r) =>
                r._field == "cpu_percent" or
                r._field == "cpu_temp"    or
                r._field == "ram_percent" or
                r._field == "heartbeat"
            )
    '''

    try:
        tables  = query_api.query(flux, org=INFLUX_ORG)
        results = []
        for table in tables:
            for record in table.records:
                results.append({
                    'time':  record.get_time().isoformat(),
                    'field': record.get_field(),
                    'value': record.get_value(),
                })
        client.close()
        return results
    except Exception as e:
        client.close()
        raise Exception(f'System health query failed: {str(e)}')


def get_latest_system_health(bucket, site_id, device_id):
    client    = get_influx_client()
    query_api = client.query_api()

    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: -10m)
            |> filter(fn: (r) => r._measurement == "system_health")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{device_id}")
            |> last()
    '''

    try:
        tables = query_api.query(flux, org=INFLUX_ORG)
        result = {}
        for table in tables:
            for record in table.records:
                result[record.get_field()] = record.get_value()
                result['last_updated']     = record.get_time().isoformat()
        client.close()
        return result
    except Exception as e:
        client.close()
        raise Exception(f'System health latest query failed: {str(e)}')
    

# ── Plant Overview Queries ─────────────────────────────────────────────────────

def _query_meter_today_energy(query_api, bucket, site_id, meter_id):
    """
    Internal: calculates today's generation from meter1.
    Uses last - first of energy_active_export_kwh since IST midnight.
    """
    start = get_ist_midnight_utc()

    flux_first = f'''
        from(bucket: "{bucket}")
            |> range(start: {start})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{meter_id}")
            |> filter(fn: (r) => r._field == "energy_active_export_kwh")
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> first()
    '''

    flux_last = f'''
        from(bucket: "{bucket}")
            |> range(start: {start})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{meter_id}")
            |> filter(fn: (r) => r._field == "energy_active_export_kwh")
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> last()
    '''

    first_val = None
    last_val  = None

    tables = query_api.query(flux_first, org=INFLUX_ORG)
    for table in tables:
        for record in table.records:
            first_val = record.get_value()

    tables = query_api.query(flux_last, org=INFLUX_ORG)
    for table in tables:
        for record in table.records:
            last_val = record.get_value()

    if first_val is not None and last_val is not None:
        return round(last_val - first_val, 2)
    return 0.0


def _query_meter_live(query_api, bucket, site_id, meter_id):
    """
    Internal: fetches all live meter1 fields in one query.
    Returns flat dict of field → value.
    """
    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: -10m)
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{meter_id}")
            |> filter(fn: (r) =>
                r._field == "active_power_total_kw"     or
                r._field == "voltage_line_ab_v"         or
                r._field == "voltage_line_bc_v"         or
                r._field == "voltage_line_ca_v"         or
                r._field == "current_phase_a"           or
                r._field == "current_phase_b"           or
                r._field == "current_phase_c"           or
                r._field == "grid_frequency_hz"         or
                r._field == "power_factor_total"        or
                r._field == "energy_active_export_kwh"
            )
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> last()
    '''

    tables     = query_api.query(flux, org=INFLUX_ORG)
    meter_data = {}

    for table in tables:
        for record in table.records:
            if not _is_fresh(record.get_time()):
                continue
            meter_data[record.get_field()] = record.get_value()

    return meter_data


def _query_inverter_status(query_api, bucket, site_id, inverter_ids):
    """
    Internal: fetches per-inverter ac_active_power_kw and energy_daily_kwh.
    Also determines online/offline status.
    """
    device_filter = ' or '.join(
        [f'r.device == "{d}"' for d in inverter_ids]
    )

    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: -10m)
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => {device_filter})
            |> filter(fn: (r) =>
                r._field == "ac_active_power_kw" or
                r._field == "energy_daily_kwh" or
                r._field == "dc_input_power_kw"
            )
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> last()
    '''

    tables       = query_api.query(flux, org=INFLUX_ORG)
    device_data  = {}
    device_times = {}

    for table in tables:
        for record in table.records:
            device = record.values.get('device')
            time   = record.get_time()

            if not _is_fresh(time):
                continue

            field = record.get_field()
            value = record.get_value()

            if device not in device_data:
                device_data[device] = {}
            device_data[device][field] = value

            if device not in device_times or time > device_times[device]:
                device_times[device] = time

    return device_data, device_times


def _query_plant_power_trend(query_api, bucket, site_id, meter_id, start, end, interval_minutes):
    """
    Internal: fetches meter1 active_power_total_kw trend.
    start/end are UTC timestamp strings.
    """
    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: {start}, stop: {end})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{meter_id}")
            |> filter(fn: (r) => r._field == "active_power_total_kw")
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> aggregateWindow(every: {interval_minutes}m, fn: mean, createEmpty: false)
    '''

    tables  = query_api.query(flux, org=INFLUX_ORG)
    results = []

    for table in tables:
        for record in table.records:
            results.append({
                'time':     record.get_time().isoformat(),
                'active_power_total_kw': abs(round(record.get_value() or 0.0, 2)),
            })

    results.sort(key=lambda x: x['time'])
    return results


def _query_irradiance_trend(query_api, bucket, site_id, device_id, start, end, interval_minutes):
    """
    Internal: fetches weather station irradiation_inclined_wm2 trend.
    Same shape/aggregation pattern as _query_plant_power_trend so the two
    series line up on the same interval buckets.
    Returns { time_iso: value } for merging onto the power trend by time.
    """
    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: {start}, stop: {end})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{device_id}")
            |> filter(fn: (r) => r._field == "irradiation_inclined_wm2")
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> aggregateWindow(every: {interval_minutes}m, fn: mean, createEmpty: false)
    '''

    tables        = query_api.query(flux, org=INFLUX_ORG)
    irradiance_map = {}

    for table in tables:
        for record in table.records:
            irradiance_map[record.get_time().isoformat()] = round(record.get_value() or 0.0, 2)

    return irradiance_map

def _query_electrical_trend(query_api, bucket, site_id, meter_id, start, end, interval_minutes):
    """
    Internal: fetches HT meter voltage/current/frequency trend for a whole
    day, aggregated every interval_minutes.
    """
    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: {start}, stop: {end})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{meter_id}")
            |> filter(fn: (r) =>
                r._field == "voltage_line_ab_v" or
                r._field == "voltage_line_bc_v" or
                r._field == "voltage_line_ca_v" or
                r._field == "current_phase_a"   or
                r._field == "current_phase_b"   or
                r._field == "current_phase_c"   or
                r._field == "grid_frequency_hz"
            )
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> aggregateWindow(every: {interval_minutes}m, fn: mean, createEmpty: false)
    '''

    tables = query_api.query(flux, org=INFLUX_ORG)

    points_by_time = {}

    for table in tables:
        for record in table.records:
            t = record.get_time().isoformat()
            field = record.get_field()
            points_by_time.setdefault(t, {'time': t})
            points_by_time[t][field] = round(record.get_value() or 0.0, 2)

    field_names = [
        'voltage_line_ab_v', 'voltage_line_bc_v', 'voltage_line_ca_v',
        'current_phase_a', 'current_phase_b', 'current_phase_c',
        'grid_frequency_hz',
    ]
    results = []
    for t in sorted(points_by_time.keys()):
        point = points_by_time[t]
        for field in field_names:
            point.setdefault(field, 0.0)
        results.append(point)

    return results


def get_plant_electrical_trend(bucket, site_id, meter_id, date_str=None, interval_minutes=5):
    """
    HT meter voltage/current/frequency trend for a selected date.
    Separate endpoint/graph from power+irradiance — min/max/last stats,
    not mean/max/last.
    """
    start_str, end_str = _resolve_ist_date_range(date_str)

    client    = get_influx_client()
    query_api = client.query_api()

    try:
        results = _query_electrical_trend(
            query_api, bucket, site_id, meter_id,
            start_str, end_str, interval_minutes
        )
        client.close()

        field_names = [
            'voltage_line_ab_v', 'voltage_line_bc_v', 'voltage_line_ca_v',
            'current_phase_a', 'current_phase_b', 'current_phase_c',
            'grid_frequency_hz',
        ]

        return {
            'data':  results,
            'stats': {
                field: _trend_stats_minmax(results, field)
                for field in field_names
            },
        }

    except Exception as e:
        client.close()
        raise Exception(f'Plant electrical trend query failed: {str(e)}')


def _trend_stats_minmax(results, field):
    """
    Internal: min/max/last over an already-fetched trend series.
    Used for electrical parameters (voltage/current/frequency) where sags
    and spikes matter more than the average — same convention as Grafana.
    """
    values = [point[field] for point in results]

    if not values:
        return {'min': 0.0, 'max': 0.0, 'last': 0.0}

    return {
        'min':  round(min(values), 2),
        'max':  round(max(values), 2),
        'last': round(values[-1], 2),
    }


def _resolve_ist_date_range(date_str):
    """
    Internal: resolves a 'YYYY-MM-DD' (or None for today) into UTC start/end
    strings for a Flux range() over that full IST day.
    Shared by every whole-day trend query (power, electrical, etc) so the
    date/today/past-day logic lives in exactly one place.
    Returns (start_str, end_str) as '%Y-%m-%dT%H:%M:%SZ' UTC strings.
    """
    ist = timezone(timedelta(hours=5, minutes=30))

    if date_str:
        try:
            requested_date = datetime.strptime(date_str, '%Y-%m-%d')
            requested_date = requested_date.replace(tzinfo=ist)
        except ValueError:
            raise Exception(f'Invalid date format: {date_str}. Use YYYY-MM-DD.')
    else:
        requested_date = datetime.now(ist).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    start_ist = requested_date.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_ist.astimezone(timezone.utc)

    now_ist   = datetime.now(ist)
    today_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)

    if start_ist.date() == today_ist.date():
        end_utc = datetime.now(timezone.utc)
    else:
        end_ist = start_ist + timedelta(days=1)
        end_utc = end_ist.astimezone(timezone.utc)

    start_str = start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    end_str   = end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    return start_str, end_str


def get_plant_overview(bucket, site_id, inverter_ids, meter_id, weather_device_id=None, dido_device_id=None, dc_capacity_kw=None, ac_capacity_kw=None, meter_energy_offset_kwh=0.0):
    """
    Plant overview — single function, four or five internal queries.
    Returns everything for the plant overview page stat cards,
    grid values, inverter status table, device summary and weather snapshot.

    weather_device_id is optional — sites without an active weather station
    pass None and the weather query is skipped entirely (no wasted call).
    Weather never fails the endpoint: offline/missing station returns zeros
    with status 'offline', same as any other offline device on this page.

    Returns:
    {
        last_updated,
        plant: {
            active_power_kw,
            energy_today_kwh,
            frequency_hz,
            power_factor,
        },
        grid: {
            voltage_ab, voltage_bc, voltage_ca,
            current_a, current_b, current_c,
        },
        inverters: [ { name, device_id, active_power_kw,
                       daily_gen_kwh, status, last_updated } ],
        device_summary: { total, online, offline },
        weather: {
            irradiation_inclined_wm2, ambient_temp_c, module_temp_c, status,
        },
    }
    """
    client    = get_influx_client()
    query_api = client.query_api()

    try:
        # Four or five internal queries, one client session
        meter_live      = _query_meter_live(query_api, bucket, site_id, meter_id)
        energy_today    = _query_meter_today_energy(query_api, bucket, site_id, meter_id)
        inv_data, inv_times = _query_inverter_status(query_api, bucket, site_id, inverter_ids)

        weather_fields = {}
        weather_time   = None
        poa_wh_m2      = 0.0
        if weather_device_id:
            weather_fields, weather_time = _query_weather_live(query_api, bucket, site_id, weather_device_id)
            poa_wh_m2      = _query_poa_irradiation(
                query_api, bucket, site_id, weather_device_id, get_ist_midnight_utc()
            )

        breaker_fields = {}
        if dido_device_id:
            breaker_fields = _query_breaker_live(query_api, bucket, site_id, dido_device_id)

        client.close()

        # Build inverter list
        inverter_list = []
        online_count  = 0
        total_dc_power = 0.0

        for device_id in inverter_ids:
            fields = inv_data.get(device_id, {})
            t      = inv_times.get(device_id)
            is_online = bool(fields)

            if is_online:
                online_count += 1
                total_dc_power += fields.get('dc_input_power_kw', 0.0)

            inverter_list.append({
                'device_id':       device_id,
                'active_power_kw': round(fields.get('ac_active_power_kw', 0.0), 2),
                'daily_gen_kwh':   round(fields.get('energy_daily_kwh', 0.0), 3),
                'status':          'online' if is_online else 'offline',
                'last_updated':    t.isoformat() if t else None,
            })

        total_inverters = len(inverter_ids)
        poa_kwh_m2      = round(poa_wh_m2 / 1000.0, 4)
        # Plant Overview only: raw meter value is negative during export (normal
        # generation). We only want to show 0 when the meter is drawing power
        # (importing, i.e. raw value positive) rather than a negative number.
        raw_active_power = meter_live.get('active_power_total_kw', 0.0)
        if raw_active_power > 0:
            active_power_kw = 0.0
        else:
            active_power_kw = round(raw_active_power * -1, 2)

        performance_ratio_pct = None
        if dc_capacity_kw and poa_kwh_m2 >= MIN_POA_KWH_M2_FOR_PR:
            performance_ratio_pct = round(
                (energy_today / (float(dc_capacity_kw) * poa_kwh_m2)) * 100, 2
            )

        cuf_pct = None
        if ac_capacity_kw:
            cuf_pct = round(
                (energy_today / (float(ac_capacity_kw) * 24)) * 100, 2
            )

        co2_avoided_today_kg = round(energy_today * CO2_AVOIDED_FACTOR_KG_PER_KWH, 2)

        return {
            'last_updated': max(
                (t for t in inv_times.values() if t),
                default=None
            ),

            'plant': {
                'active_power_kw':  active_power_kw,
                'energy_today_kwh': energy_today,
                'frequency_hz':     round(meter_live.get('grid_frequency_hz', 0.0), 2),
                'power_factor':     round(meter_live.get('power_factor_total', 0.0), 2),
                'dc_capacity_kw':   float(dc_capacity_kw) if dc_capacity_kw else None,
                'ac_capacity_kw':   float(ac_capacity_kw) if ac_capacity_kw else None,
                'energy_active_export_kwh': round(
                    meter_live.get('energy_active_export_kwh', 0.0) + meter_energy_offset_kwh, 2
                ) if meter_live else 0.0,
            },

            'grid': {
                'voltage_ab': round(meter_live.get('voltage_line_ab_v', 0.0), 3),
                'voltage_bc': round(meter_live.get('voltage_line_bc_v', 0.0), 3),
                'voltage_ca': round(meter_live.get('voltage_line_ca_v', 0.0), 3),
                'current_a':  round(meter_live.get('current_phase_a', 0.0), 2),
                'current_b':  round(meter_live.get('current_phase_b', 0.0), 2),
                'current_c':  round(meter_live.get('current_phase_c', 0.0), 2),
            },

            'inverters': inverter_list,

            'device_summary': {
                'total':   total_inverters,
                'online':  online_count,
                'offline': total_inverters - online_count,
            },

            'weather': {
                'irradiation_inclined_wm2': round(weather_fields.get('irradiation_inclined_wm2', 0.0), 2),
                'ambient_temp_c':           round(weather_fields.get('ambient_temp_c', 0.0), 2),
                'module_temp_c':            round(weather_fields.get('module_temp_c', 0.0), 2),
                'status':                   'online' if weather_fields else 'offline',
                'last_updated':             weather_time.isoformat() if weather_time else None,
            },

            'performance': {
                'performance_ratio_pct':       performance_ratio_pct,
                'cuf_pct':                     cuf_pct,
                'poa_irradiation_kwh_m2':      poa_kwh_m2,
                'dc_power_total_kw':           round(total_dc_power, 2),
                'co2_avoided_today_kg':   co2_avoided_today_kg,
            },
            
            'breaker_status': breaker_fields.get('breaker_status'),
            'service_status': breaker_fields.get('service_status'),
        }

    except Exception as e:
        client.close()
        raise Exception(f'Plant overview query failed: {str(e)}')

def _trend_stats(results, field):
    """
    Internal: max/mean/last over an already-fetched trend series.
    No Influx call — pure Python over the list get_plant_power_trend already
    has in memory, so this costs nothing extra against the call budget.
    results must be time-sorted (both trend queries already sort by time).
    """
    values = [point[field] for point in results]

    if not values:
        return {'max': 0.0, 'mean': 0.0, 'last': 0.0}

    return {
        'max':  round(max(values), 2),
        'mean': round(sum(values) / len(values), 2),
        'last': round(values[-1], 2),
    }


def get_plant_power_trend(bucket, site_id, meter_id, weather_device_id=None, date_str=None, interval_minutes=5):
    """
    Plant power trend for a selected date.
    date_str: 'YYYY-MM-DD' in IST. Defaults to today if not provided.
    Returns meter1 active_power_total_kw aggregated every interval_minutes.

    Returns:
    [
        { 'time': '2026-06-03T04:30:00Z', 'power_kw': 0.0 },
        { 'time': '2026-06-03T05:00:00Z', 'power_kw': 104.5 },
        ...
    ]
    """
    start_str, end_str = _resolve_ist_date_range(date_str)

    client    = get_influx_client()
    query_api = client.query_api()

    try:
        results = _query_plant_power_trend(
            query_api, bucket, site_id, meter_id,
            start_str, end_str, interval_minutes
        )

        irradiance_map = {}
        if weather_device_id:
            irradiance_map = _query_irradiance_trend(
                query_api, bucket, site_id, weather_device_id,
                start_str, end_str, interval_minutes
            )

        client.close()
        for point in results:
            point['irradiation_inclined_wm2'] = irradiance_map.get(point['time'], 0.0)
        return {
            'data':  results,
            'stats': {
                'active_power_total_kw':    _trend_stats(results, 'active_power_total_kw'),
                'irradiation_inclined_wm2': _trend_stats(results, 'irradiation_inclined_wm2'),
            },
        }

    except Exception as e:
        client.close()
        raise Exception(f'Plant power trend query failed: {str(e)}')
    

    # ── Inverter Overview Queries ──────────────────────────────────────────────────

def get_inverter_overview(bucket, site_id, inverter_ids, weather_device_id=None, dc_capacity_kw=None):
    """
    Fetches all live inverter data in one query.
    Returns summary (totals) + per inverter breakdown.

    Fields fetched per inverter:
        ac_active_power_kw, energy_daily_kwh, energy_total_kwh,
        grid_frequency_hz, ac_power_factor, ac_reactive_power_kvar,
        inverter_efficiency_pct
    """
    client    = get_influx_client()
    query_api = client.query_api()

    device_filter = ' or '.join(
        [f'r.device == "{d}"' for d in inverter_ids]
    )

    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: -10m)
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => {device_filter})
            |> filter(fn: (r) =>
                r._field == "ac_active_power_kw"      or
                r._field == "energy_daily_kwh"         or
                r._field == "energy_total_kwh"         or
                r._field == "grid_frequency_hz"        or
                r._field == "ac_power_factor"          or
                r._field == "ac_reactive_power_kvar"   or
                r._field == "inverter_efficiency_pct"
            )
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> last()
    '''

    try:
        tables       = query_api.query(flux, org=INFLUX_ORG)

        poa_kwh_m2 = 0.0
        if weather_device_id:
            poa_wh_m2  = _query_poa_irradiation(
                query_api, bucket, site_id, weather_device_id, get_ist_midnight_utc()
            )
            poa_kwh_m2 = round(poa_wh_m2 / 1000.0, 4)
        client.close()

        # Collect per device
        device_data  = {}
        device_times = {}

        for table in tables:
            for record in table.records:
                if not _is_fresh(record.get_time()):
                    continue

                device = record.values.get('device')
                field  = record.get_field()
                value  = record.get_value()
                time   = record.get_time()

                if device not in device_data:
                    device_data[device] = {}
                device_data[device][field] = value

                if device not in device_times or time > device_times[device]:
                    device_times[device] = time

        # Build per inverter list and totals
        inverter_list        = []
        total_active_power   = 0.0
        total_daily_gen      = 0.0
        online_count         = 0

        dc_capacity_per_inverter = (
            float(dc_capacity_kw) / len(inverter_ids)
            if dc_capacity_kw and len(inverter_ids) > 0 else None
        )

        for device_id in inverter_ids:
            fields    = device_data.get(device_id, {})
            t         = device_times.get(device_id)
            is_online = bool(fields)

            if is_online:
                online_count += 1

            active_power = abs(round(fields.get('ac_active_power_kw', 0.0), 2))
            daily_gen    = abs(round(fields.get('energy_daily_kwh', 0.0), 3))

            total_active_power += active_power
            total_daily_gen    += daily_gen

            inverter_pr_pct = None
            if dc_capacity_per_inverter and poa_kwh_m2 >= MIN_POA_KWH_M2_FOR_PR:
                inverter_pr_pct = round(
                    (daily_gen / (dc_capacity_per_inverter * poa_kwh_m2)) * 100, 2
                )

            inverter_list.append({
                'device_id':               device_id,
                'ac_active_power_kw':      active_power,
                'energy_daily_kwh':        daily_gen,
                'energy_total_kwh':        abs(round(fields.get('energy_total_kwh', 0.0), 2)),
                'ac_reactive_power_kvar':  abs(round(fields.get('ac_reactive_power_kvar', 0.0), 2)),
                'ac_power_factor':         round(fields.get('ac_power_factor', 0.0), 2),
                'grid_frequency_hz':       round(fields.get('grid_frequency_hz', 0.0), 2),
                'inverter_efficiency_pct': round(fields.get('inverter_efficiency_pct', 0.0), 1),
                'performance_ratio_pct':   inverter_pr_pct,
                'status':                  'online' if is_online else 'offline',
                'last_updated':            t.isoformat() if t else None,
            })

        fleet_pr_pct = None
        if dc_capacity_kw and poa_kwh_m2 >= MIN_POA_KWH_M2_FOR_PR:
            fleet_pr_pct = round(
                (total_daily_gen / (float(dc_capacity_kw) * poa_kwh_m2)) * 100, 2
            )

        return {
            'summary': {
                'total_ac_active_power_kw': round(total_active_power, 2),
                'total_energy_daily_kwh':   round(total_daily_gen, 3),
                'online_count':             online_count,
                'total_count':              len(inverter_ids),
                'performance_ratio_pct':    fleet_pr_pct,
                'poa_irradiation_kwh_m2':   poa_kwh_m2,
            },
            'inverters': inverter_list,
        }

    except Exception as e:
        client.close()
        raise Exception(f'Inverter overview query failed: {str(e)}')


def get_inverter_power_trend(bucket, site_id, inverter_ids, date_str=None, interval_minutes=5):
    """
    Inverter power trend for a selected date.
    Sums ac_active_power_kw across all inverters per time bucket.
    date_str: 'YYYY-MM-DD' in IST. Defaults to today if not provided.
    """
    ist = timezone(timedelta(hours=5, minutes=30))

    if date_str:
        try:
            requested_date = datetime.strptime(date_str, '%Y-%m-%d')
            requested_date = requested_date.replace(tzinfo=ist)
        except ValueError:
            raise Exception(f'Invalid date format: {date_str}. Use YYYY-MM-DD.')
    else:
        requested_date = datetime.now(ist).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    # Start = IST midnight → UTC
    start_ist    = requested_date.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc    = start_ist.astimezone(timezone.utc)

    # End = now if today, else next midnight
    now_ist      = datetime.now(ist)
    today_ist    = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)

    if start_ist.date() == today_ist.date():
        end_utc  = datetime.now(timezone.utc)
    else:
        end_ist  = start_ist + timedelta(days=1)
        end_utc  = end_ist.astimezone(timezone.utc)

    start_str    = start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    end_str      = end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    device_filter = ' or '.join(
        [f'r.device == "{d}"' for d in inverter_ids]
    )

    client    = get_influx_client()
    query_api = client.query_api()

    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: {start_str}, stop: {end_str})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => {device_filter})
            |> filter(fn: (r) => r._field == "ac_active_power_kw")
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> aggregateWindow(every: {interval_minutes}m, fn: mean, createEmpty: false)
            |> pivot(rowKey: ["_time"], columnKey: ["device"], valueColumn: "_value")
    '''

    try:
        tables  = query_api.query(flux, org=INFLUX_ORG)
        client.close()

        results = []
        for table in tables:
            for record in table.records:
                total = sum(
                    abs(record.values.get(d) or 0.0)
                    for d in inverter_ids
                )
                results.append({
                    'time':     record.get_time().isoformat(),
                    'power_kw': round(total, 2),
                })

        results.sort(key=lambda x: x['time'])
        return results

    except Exception as e:
        client.close()
        raise Exception(f'Inverter power trend query failed: {str(e)}')


# ── Inverter Detail Page Queries ──────────────────────────────────────────────

def get_inverter_detail(bucket, site_id, device_id, weather_device_id=None, dc_capacity_per_inverter=None):
    client    = get_influx_client()
    query_api = client.query_api()

    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: -10m)
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{device_id}")
            |> filter(fn: (r) =>
                r._field == "ac_active_power_kw"      or
                r._field == "energy_daily_kwh"        or
                r._field == "energy_total_kwh"        or
                r._field == "ac_power_factor"         or
                r._field == "inverter_efficiency_pct" or
                r._field == "grid_frequency_hz"       or
                r._field == "ac_reactive_power_kvar"  or
                r._field == "internal_temp_c"         or
                r._field == "grid_voltage_ab_v"       or
                r._field == "grid_voltage_bc_v"       or
                r._field == "grid_voltage_ca_v"
            )
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> last()
    '''

    try:
        tables = query_api.query(flux, org=INFLUX_ORG)
        
        poa_kwh_m2 = 0.0
        if weather_device_id:
            poa_wh_m2  = _query_poa_irradiation(
                query_api, bucket, site_id, weather_device_id, get_ist_midnight_utc()
            )
            poa_kwh_m2 = round(poa_wh_m2 / 1000.0, 4)
        client.close()

        fields    = {}
        last_time = None

        for table in tables:
            for record in table.records:
                if not _is_fresh(record.get_time()):
                    continue

                fields[record.get_field()] = record.get_value()
                t = record.get_time()
                if last_time is None or t > last_time:
                    last_time = t

        is_online    = bool(fields)
        active_power = abs(round(fields.get('ac_active_power_kw', 0.0), 2))
        daily_gen    = abs(round(fields.get('energy_daily_kwh', 0.0), 3))

        performance_ratio_pct = None
        if dc_capacity_per_inverter and poa_kwh_m2 >= MIN_POA_KWH_M2_FOR_PR:
            performance_ratio_pct = round(
                (daily_gen / (dc_capacity_per_inverter * poa_kwh_m2)) * 100, 2
            )
        
        return {
            'device_id':               device_id,
            'ac_active_power_kw':      active_power,
            'energy_daily_kwh':        daily_gen,
            'energy_total_kwh':        abs(round(fields.get('energy_total_kwh', 0.0), 2)),
            'ac_power_factor':         round(fields.get('ac_power_factor', 0.0), 2),
            'inverter_efficiency_pct': round(fields.get('inverter_efficiency_pct', 0.0), 1),
            'performance_ratio_pct':   performance_ratio_pct,
            'poa_irradiation_kwh_m2':  poa_kwh_m2,
            'grid_frequency_hz':       round(fields.get('grid_frequency_hz', 0.0), 2),
            'ac_reactive_power_kvar':  abs(round(fields.get('ac_reactive_power_kvar', 0.0), 2)),
            'internal_temp_c':         round(fields.get('internal_temp_c', 0.0), 1),
            'grid_voltage_ab_v':       round(fields.get('grid_voltage_ab_v', 0.0), 1),
            'grid_voltage_bc_v':       round(fields.get('grid_voltage_bc_v', 0.0), 1),
            'grid_voltage_ca_v':       round(fields.get('grid_voltage_ca_v', 0.0), 1),
            'status':                  'online' if is_online else 'offline',
            'last_updated':            last_time.isoformat() if last_time else None,
        }

    except Exception as e:
        client.close()
        raise Exception(f'Inverter detail query failed: {str(e)}')
    

def get_inverter_detail_power_trend(bucket, site_id, device_id, date_str=None, interval_minutes=5):
    """
    Powers both the 'DC Input vs Active Power' and 'Active vs Reactive Power' charts
    on the inverter detail page — one device, one date, one query, three fields.
    """
    ist = timezone(timedelta(hours=5, minutes=30))

    if date_str:
        try:
            requested_date = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=ist)
        except ValueError:
            raise Exception(f'Invalid date format: {date_str}. Use YYYY-MM-DD.')
    else:
        requested_date = datetime.now(ist).replace(hour=0, minute=0, second=0, microsecond=0)

    start_ist = requested_date.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_ist.astimezone(timezone.utc)

    now_ist   = datetime.now(ist)
    today_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)

    if start_ist.date() == today_ist.date():
        end_utc = datetime.now(timezone.utc)
    else:
        end_utc = (start_ist + timedelta(days=1)).astimezone(timezone.utc)

    start_str = start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    end_str   = end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    client    = get_influx_client()
    query_api = client.query_api()

    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: {start_str}, stop: {end_str})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{device_id}")
            |> filter(fn: (r) =>
                r._field == "dc_input_power_kw"     or
                r._field == "ac_active_power_kw"    or
                r._field == "ac_reactive_power_kvar"
            )
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> aggregateWindow(every: {interval_minutes}m, fn: mean, createEmpty: false)
            |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
    '''

    try:
        tables  = query_api.query(flux, org=INFLUX_ORG)
        client.close()

        results = []
        for table in tables:
            for record in table.records:
                results.append({
                    'time':                   record.get_time().isoformat(),
                    'dc_input_power_kw':      abs(round(record.values.get('dc_input_power_kw') or 0.0, 2)),
                    'ac_active_power_kw':     abs(round(record.values.get('ac_active_power_kw') or 0.0, 2)),
                    'ac_reactive_power_kvar': abs(round(record.values.get('ac_reactive_power_kvar') or 0.0, 2)),
                })

        results.sort(key=lambda x: x['time'])
        return results

    except Exception as e:
        client.close()
        raise Exception(f'Inverter detail power trend query failed: {str(e)}')
    

def get_inverter_daily_energy(bucket, site_id, device_id, days=7):
    """
    One inverter's own daily generation for the last N days.
    Uses max() per day on energy_daily_kwh since it resets to 0 at midnight.
    """
    client    = get_influx_client()
    query_api = client.query_api()
    start     = get_n_days_ago_midnight_utc(days - 1)
    ist_offset = '5h30m'

    flux = f'''
        import "timezone"

        option location = timezone.fixed(offset: {ist_offset})

        from(bucket: "{bucket}")
            |> range(start: {start})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{device_id}")
            |> filter(fn: (r) => r._field == "energy_daily_kwh")
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> aggregateWindow(every: 1d, fn: max, createEmpty: false, timeSrc: "_start")
    '''

    try:
        tables  = query_api.query(flux, org=INFLUX_ORG)
        client.close()

        results = []
        ist_tz  = timezone(timedelta(hours=5, minutes=30))

        for table in tables:
            for record in table.records:
                ist_time = record.get_time().astimezone(ist_tz)
                results.append({
                    'date':       ist_time.strftime('%Y-%m-%d'),
                    'energy_kwh': abs(round(record.get_value(), 2)),
                })

        results.sort(key=lambda x: x['date'])
        return results

    except Exception as e:
        client.close()
        raise Exception(f'Inverter daily energy query failed: {str(e)}')
    

def get_all_inverters_pv_strings(bucket, site_id, inverter_ids):
    """
    Fetches PV string currents for every inverter at a site in a single query.
    Returns { 'inverter1': { '01': 11.40, '02': 0.0, ... }, 'inverter2': {...}, ... }
    Stale readings (older than STALE_AFTER_SECONDS) are dropped rather than
    shown as a last-known value, matching the same rule as every other
    live snapshot in this file.
    """
    client    = get_influx_client()
    query_api = client.query_api()

    device_filter = ' or '.join(
        [f'r.device == "{d}"' for d in inverter_ids]
    )

    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: -10m)
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => {device_filter})
            |> filter(fn: (r) => r._field =~ /^pv_string_\\d+_current_a$/)
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> last()
    '''

    try:
        tables = query_api.query(flux, org=INFLUX_ORG)
        client.close()

        device_pv_data = {d: {} for d in inverter_ids}

        for table in tables:
            for record in table.records:
                if not _is_fresh(record.get_time()):
                    continue

                device = record.values.get('device')
                match  = re.match(r'^pv_string_(\d+)_current_a$', record.get_field())
                if match and device in device_pv_data:
                    device_pv_data[device][match.group(1)] = record.get_value()

        return device_pv_data

    except Exception as e:
        client.close()
        raise Exception(f'PV strings query failed: {str(e)}')

    # ── Meter Overview Query ───────────────────────────────────────────────────────

def get_meter_overview(bucket, sites_with_meters):
    """
    Fetches live data for all meters across one or more sites
    (main site + optional substation).

    Args:
        bucket             : InfluxDB bucket (from Customer.influx_bucket)
        sites_with_meters  : list of dicts, one per site to query:
            [
                {
                    'influx_site_id': 'siteA',
                    'location': 'MAIN',
                    'meters': [
                        {'influx_device_id': 'meter1', 'name': 'Main Meter', 'pk': 1},
                        ...
                    ]
                },
                {
                    'influx_site_id': 'siteA-gss',
                    'location': 'SUBSTATION',
                    'meters': [...]
                }
            ]

    Returns a flat list of meter dicts, each tagged with its location and
    Postgres pk so the frontend never has to worry about influx_device_id
    collisions between main site and substation.
    """
    client    = get_influx_client()
    query_api = client.query_api()

    all_meters_result = []

    try:
        for site_group in sites_with_meters:
            site_id = site_group['influx_site_id']
            site_type = site_group['site_type']
            meters   = site_group['meters']

            if not meters:
                continue

            device_filter = ' or '.join(
                [f'r.device == "{m["influx_device_id"]}"' for m in meters]
            )

            flux = f'''
                from(bucket: "{bucket}")
                    |> range(start: -10m)
                    |> filter(fn: (r) => r._measurement == "solar_data")
                    |> filter(fn: (r) => r.site == "{site_id}")
                    |> filter(fn: (r) => {device_filter})
                    |> filter(fn: (r) =>
                        r._field == "active_power_total_kw"          or
                        r._field == "reactive_power_total_kvar"      or
                        r._field == "apparent_power_total_kva"       or
                        r._field == "energy_active_export_kwh"       or
                        r._field == "energy_active_import_kwh"       or
                        r._field == "energy_active_net_kwh"          or
                        r._field == "energy_reactive_export_kvarh"   or
                        r._field == "energy_reactive_import_kvarh"   or
                        r._field == "voltage_line_ab_v"              or
                        r._field == "voltage_line_bc_v"              or
                        r._field == "voltage_line_ca_v"              or
                        r._field == "current_phase_a"                or
                        r._field == "current_phase_b"                or
                        r._field == "current_phase_c"                or
                        r._field == "grid_frequency_hz"              or
                        r._field == "power_factor_total"
                    )
                    |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
                    |> last()
            '''

            tables       = query_api.query(flux, org=INFLUX_ORG)
            device_data  = {}
            device_times = {}

            for table in tables:
                for record in table.records:

                    if not _is_fresh(record.get_time()):
                        continue

                    device = record.values.get('device')
                    field  = record.get_field()
                    value  = record.get_value()
                    time   = record.get_time()

                    if device not in device_data:
                        device_data[device] = {}
                    device_data[device][field] = value

                    if device not in device_times or time > device_times[device]:
                        device_times[device] = time

            # Build result for each meter in this site group, in order
            for meter in meters:
                influx_id = meter['influx_device_id']
                fields    = device_data.get(influx_id, {})
                t         = device_times.get(influx_id)
                is_online = bool(fields)
                offset    = meter.get('energy_offset_kwh', 0.0)

                raw_export_kwh = fields.get('energy_active_export_kwh', 0.0)
                corrected_export_kwh = raw_export_kwh + offset if is_online else 0.0

                energy_today  = _query_meter_today_energy(query_api, bucket, site_id, influx_id)

                all_meters_result.append({
                    'device_pk':                   meter['pk'],
                    'device_id':                    influx_id,
                    'name':                          meter['name'],
                    'site_type':                    site_type, 
                    'active_power_total_kw':         abs(round(fields.get('active_power_total_kw', 0.0), 2)),
                    'reactive_power_total_kvar':      round(fields.get('reactive_power_total_kvar', 0.0), 2),
                    'apparent_power_total_kva':       round(fields.get('apparent_power_total_kva', 0.0), 2),
                    'energy_active_export_kwh':       round(corrected_export_kwh, 2),
                    'energy_active_import_kwh':        round(fields.get('energy_active_import_kwh', 0.0), 2),
                    'energy_active_net_kwh':           round(fields.get('energy_active_net_kwh', 0.0), 2),
                    'energy_reactive_export_kvarh':    round(fields.get('energy_reactive_export_kvarh', 0.0), 2),
                    'energy_reactive_import_kvarh':    round(fields.get('energy_reactive_import_kvarh', 0.0), 2),
                    'voltage_line_ab_v':               round(fields.get('voltage_line_ab_v', 0.0), 2),
                    'voltage_line_bc_v':               round(fields.get('voltage_line_bc_v', 0.0), 2),
                    'voltage_line_ca_v':               round(fields.get('voltage_line_ca_v', 0.0), 2),
                    'current_phase_a':                 round(fields.get('current_phase_a', 0.0), 2),
                    'current_phase_b':                 round(fields.get('current_phase_b', 0.0), 2),
                    'current_phase_c':                 round(fields.get('current_phase_c', 0.0), 2),
                    'grid_frequency_hz':               round(fields.get('grid_frequency_hz', 0.0), 2),
                    'power_factor_total':              round(fields.get('power_factor_total', 0.0), 2),
                    'energy_today_kwh':                energy_today,
                    'status':                          'online' if is_online else 'offline',
                    'last_updated':                    t.isoformat() if t else None,
                })

        client.close()
        return all_meters_result

    except Exception as e:
        client.close()
        raise Exception(f'Meter overview query failed: {str(e)}')
    

# Analytics Data
def get_analytics_data(bucket, site_id, series_map, date_str=None, interval_minutes=5):
    """
    series_map: { series_key: {'device': 'inverter1', 'field': 'ac_active_power_kw'} }
    series_key is caller-defined and unique per requested device+metric combo
    (view uses '{influx_device_id}__{metric_key}').

    Returns merged, time-aligned points:
    [
        { 'time': '2026-06-18T04:30:00Z', 'inverter1__active_power': 12.4, 'weather_station1__irradiation': 340.0 },
        ...
    ]
    Points only carry keys for series that actually had data at that timestamp
    (no forced zero-fill across series with different reporting devices).
    """
    ist = timezone(timedelta(hours=5, minutes=30))

    if date_str:
        try:
            requested_date = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=ist)
        except ValueError:
            raise Exception(f'Invalid date format: {date_str}. Use YYYY-MM-DD.')
    else:
        requested_date = datetime.now(ist).replace(hour=0, minute=0, second=0, microsecond=0)

    start_ist = requested_date.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_ist.astimezone(timezone.utc)

    now_ist   = datetime.now(ist)
    today_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)

    if start_ist.date() == today_ist.date():
        end_utc = datetime.now(timezone.utc)
    else:
        end_utc = (start_ist + timedelta(days=1)).astimezone(timezone.utc)

    start_str = start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    end_str   = end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    match_clauses = ' or '.join(
        f'(r.device == "{s["device"]}" and r._field == "{s["field"]}")'
        for s in series_map.values()
    )

    # Reverse lookup: (device, field) -> series_key, for reassembling results
    key_by_device_field = {
        (s['device'], s['field']): key for key, s in series_map.items()
    }

    client    = get_influx_client()
    query_api = client.query_api()

    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: {start_str}, stop: {end_str})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => {match_clauses})
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> aggregateWindow(every: {interval_minutes}m, fn: mean, createEmpty: false)
    '''


    try:
        tables  = query_api.query(flux, org=INFLUX_ORG)
        client.close()

        # Group by timestamp, merging every series' value into that timestamp's point
        points_by_time = {}

        for table in tables:
            for record in table.records:
                device = record.values.get('device')
                field  = record.get_field()
                key    = key_by_device_field.get((device, field))
                if not key:
                    continue

                time_iso = record.get_time().isoformat()
                if time_iso not in points_by_time:
                    points_by_time[time_iso] = {'time': time_iso}
                points_by_time[time_iso][key] = round(record.get_value(), 3)

        results = sorted(points_by_time.values(), key=lambda p: p['time'])
        return results

    except Exception as e:
        client.close()
        raise Exception(f'Analytics query failed: {str(e)}')
    

# ── Installer Overview Queries ─────────────────────────────────────────────────

def _query_installer_live_snapshot(query_api, bucket, site_meter_map, site_inverters_map):
    """
    Live active power per meter + inverter online count per site, one query.
    site_meter_map:     { influx_site_id: meter_influx_device_id }
    site_inverters_map: { influx_site_id: [inverter_influx_device_ids] }
    Returns: { influx_site_id: { active_power_kw, meter_online, inverters_online, inverters_total, last_updated } }
    """
    site_ids = list(site_meter_map.keys())
    site_filter   = ' or '.join([f'r.site == "{s}"' for s in site_ids])

    all_devices   = set(site_meter_map.values())
    for inv_ids in site_inverters_map.values():
        all_devices.update(inv_ids)
    device_filter = ' or '.join([f'r.device == "{d}"' for d in all_devices])

    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: -10m)
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => {site_filter})
            |> filter(fn: (r) => {device_filter})
            |> filter(fn: (r) =>
                r._field == "active_power_total_kw" or
                r._field == "ac_active_power_kw"
            )
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> last()
    '''

    tables = query_api.query(flux, org=INFLUX_ORG)

    raw = {}  # { (site_tag, device_tag): { field: value, _time: time } }
    for table in tables:
        for record in table.records:
            if not _is_fresh(record.get_time()):
                continue
            key = (record.values.get('site'), record.values.get('device'))
            if key not in raw:
                raw[key] = {}
            raw[key][record.get_field()] = record.get_value()
            raw[key]['_time'] = record.get_time()

    results = {}
    for influx_site_id in site_ids:
        meter_id  = site_meter_map.get(influx_site_id)
        inv_ids   = site_inverters_map.get(influx_site_id, [])
        meter_rec = raw.get((influx_site_id, meter_id), {}) if meter_id else {}
        last_time = meter_rec.get('_time')

        results[influx_site_id] = {
            'active_power_kw':  abs(round(meter_rec.get('active_power_total_kw', 0.0), 2)),
            'meter_online':     bool(meter_rec),
            'inverters_online': sum(1 for inv_id in inv_ids if raw.get((influx_site_id, inv_id))),
            'inverters_total':  len(inv_ids),
            'last_updated':     last_time.isoformat() if last_time else None,
        }

    return results


def _query_installer_energy_today(query_api, bucket, site_meter_map):
    """
    Energy today (last - first since IST midnight) for all meters in this bucket.
    site_meter_map: { influx_site_id: meter_influx_device_id }
    Returns: { influx_site_id: energy_today_kwh }
    """
    site_ids      = list(site_meter_map.keys())
    site_filter   = ' or '.join([f'r.site == "{s}"' for s in site_ids])
    meter_ids     = list(set(site_meter_map.values()))
    device_filter = ' or '.join([f'r.device == "{d}"' for d in meter_ids])
    start         = get_ist_midnight_utc()
    ist_offset    = '5h30m'

    # aggregateWindow(every: 24h, timeSrc: "_start") ensures both first and last
    # share the same _time (IST midnight), so pivot can match them correctly.
    flux = f'''
        import "timezone"

        option location = timezone.fixed(offset: {ist_offset})

        day_first = from(bucket: "{bucket}")
            |> range(start: {start})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => {site_filter})
            |> filter(fn: (r) => {device_filter})
            |> filter(fn: (r) => r._field == "energy_active_export_kwh")
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> aggregateWindow(every: 24h, fn: first, createEmpty: false, timeSrc: "_start")
            |> map(fn: (r) => ({{r with _field: "v_first"}}))

        day_last = from(bucket: "{bucket}")
            |> range(start: {start})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => {site_filter})
            |> filter(fn: (r) => {device_filter})
            |> filter(fn: (r) => r._field == "energy_active_export_kwh")
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> aggregateWindow(every: 24h, fn: last, createEmpty: false, timeSrc: "_start")
            |> map(fn: (r) => ({{r with _field: "v_last"}}))

        union(tables: [day_first, day_last])
            |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
            |> map(fn: (r) => ({{r with _value: r.v_last - r.v_first}}))
    '''

    tables = query_api.query(flux, org=INFLUX_ORG)

    # site + device tags are preserved through union → pivot → map
    energy_map = {}  # { (site_tag, device_tag): energy_kwh }
    for table in tables:
        for record in table.records:
            key = (record.values.get('site'), record.values.get('device'))
            energy_map[key] = abs(round(record.get_value(), 2))

    return {
        influx_site_id: energy_map.get((influx_site_id, site_meter_map[influx_site_id]), 0.0)
        for influx_site_id in site_ids
    }


def get_installer_overview(bucket_groups):
    """
    Fires 2 Flux queries per bucket (live snapshot + energy today).
    bucket_groups: {
        bucket_str: {
            'meter_map':     { influx_site_id: meter_influx_device_id },
            'inverters_map': { influx_site_id: [inv_influx_device_ids] },
        }
    }
    Returns: { influx_site_id: { active_power_kw, energy_today_kwh, meter_online,
                                  inverters_online, inverters_total, last_updated } }
    """
    client    = get_influx_client()
    query_api = client.query_api()
    results   = {}

    try:
        for bucket, group in bucket_groups.items():
            live   = _query_installer_live_snapshot(
                query_api, bucket, group['meter_map'], group['inverters_map']
            )
            energy = _query_installer_energy_today(
                query_api, bucket, group['meter_map']
            )

            for influx_site_id in group['meter_map']:
                results[influx_site_id] = {
                    **live.get(influx_site_id, {
                        'active_power_kw': 0.0, 'meter_online': False,
                        'inverters_online': 0, 'inverters_total': 0, 'last_updated': None,
                    }),
                    'energy_today_kwh': energy.get(influx_site_id, 0.0),
                }

        client.close()

    except Exception as e:
        client.close()
        raise Exception(f'Installer overview query failed: {str(e)}')

    return results

# Weather Station 
def get_weather_snapshot(bucket, site_id, device_id):
    """
    Live snapshot for the weather station page.
    Delegates to the shared _query_weather_live (staleness-gated),
    so this page and get_plant_overview never disagree on what "online" means.
    """
    client    = get_influx_client()
    query_api = client.query_api()

    try:
        fields, last_time = _query_weather_live(query_api, bucket, site_id, device_id)
        client.close()

        is_online = bool(fields)

        return {
            'irradiation_inclined_wm2': round(fields.get('irradiation_inclined_wm2', 0.0), 2),
            'ambient_temp_c':           round(fields.get('ambient_temp_c', 0.0), 2),
            'module_temp_c':            round(fields.get('module_temp_c', 0.0), 2),
            'wind_speed_ms':            round(fields.get('wind_speed_ms', 0.0), 2),
            'wind_direction_deg':       round(fields.get('wind_direction_deg', 0.0), 1),
            'pressure_hpa':             round(fields.get('pressure_hpa', 0.0), 2),
            'rain_mm':                  round(fields.get('rain_mm', 0.0), 2),
            'humidity_pct':             round(fields.get('humidity_pct', 0.0), 1),
            'status':                   'online' if is_online else 'offline',
            'last_updated':             last_time.isoformat() if last_time else None,
        }

    except Exception as e:
        client.close()
        raise Exception(f'Weather snapshot query failed: {str(e)}')
    

def _query_weather_live(query_api, bucket, site_id, device_id):
    """
    Internal: fetches live weather station fields, gated on staleness.
    Returns (fields, last_time) — fields is {} and last_time is None
    if no fresh data was found.
    """
    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: -10m)
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{device_id}")
            |> filter(fn: (r) =>
                r._field == "irradiation_inclined_wm2" or
                r._field == "ambient_temp_c"           or
                r._field == "module_temp_c"            or
                r._field == "wind_speed_ms"            or
                r._field == "wind_direction_deg"       or
                r._field == "pressure_hpa"             or
                r._field == "rain_mm"                  or
                r._field == "humidity_pct"
            )
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> last()
    '''

    tables       = query_api.query(flux, org=INFLUX_ORG)
    weather_data = {}
    last_time    = None

    for table in tables:
        for record in table.records:
            if not _is_fresh(record.get_time()):
                continue

            weather_data[record.get_field()] = record.get_value()
            t = record.get_time()
            if last_time is None or t > last_time:
                last_time = t

    return weather_data, last_time

def _query_poa_irradiation(query_api, bucket, site_id, device_id, start):
    """
    Internal: true cumulative plane-of-array irradiation since IST midnight,
    using Flux's integral() to do the area-under-curve calc server-side.
    irradiation_inclined_wm2 is an instantaneous rate (W/m²); integrating
    it over time with unit: 1h gives Wh/m² directly.
    Returns Wh/m² (0.0 if no weather data in range).
    """
    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: {start})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{device_id}")
            |> filter(fn: (r) => r._field == "irradiation_inclined_wm2")
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> integral(unit: 1h)
    '''

    tables = query_api.query(flux, org=INFLUX_ORG)

    for table in tables:
        for record in table.records:
            return record.get_value() or 0.0

    return 0.0

# Daily Snapshot to Posgres

def _query_meter_energy_for_day(query_api, bucket, site_id, meter_id, start, end):
    """
    Internal: meter energy generated over a specific IST day (start/end
    already resolved via _resolve_ist_date_range). Last-minus-first on the
    cumulative export counter, range-bounded — safe for past dates.

    Returns (energy_kwh, status):
        (float, 'ok')       — trustworthy figure, may legitimately be 0.0
        (None,  'no_data')  — meter reported nothing in this range
        (None,  'anomaly')  — counter went backwards (rollover / meter swap /
                              bad packet). Never store this as a real number.
    """
    flux_first = f'''
        from(bucket: "{bucket}")
            |> range(start: {start}, stop: {end})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{meter_id}")
            |> filter(fn: (r) => r._field == "energy_active_export_kwh")
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> first()
    '''
    flux_last = f'''
        from(bucket: "{bucket}")
            |> range(start: {start}, stop: {end})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{meter_id}")
            |> filter(fn: (r) => r._field == "energy_active_export_kwh")
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> last()
    '''

    first_val = None
    last_val  = None

    tables = query_api.query(flux_first, org=INFLUX_ORG)
    for table in tables:
        for record in table.records:
            first_val = record.get_value()

    tables = query_api.query(flux_last, org=INFLUX_ORG)
    for table in tables:
        for record in table.records:
            last_val = record.get_value()

    if first_val is None or last_val is None:
        return None, 'no_data'

    delta = last_val - first_val
    if delta < 0:
        # Cumulative counter moved backwards — this is never a valid
        # generation figure. Flag it; do not store it.
        return None, 'anomaly'

    return round(delta, 3), 'ok'


def _query_poa_irradiation_for_day(query_api, bucket, site_id, device_id, start, end):
    """
    Internal: POA irradiation integrated over a specific IST day.
    Same integral() logic as _query_poa_irradiation, range-bounded.
    Returns Wh/m² (0.0 if no weather data in range).
    """
    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: {start}, stop: {end})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{device_id}")
            |> filter(fn: (r) => r._field == "irradiation_inclined_wm2")
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> integral(unit: 1h)
    '''

    tables = query_api.query(flux, org=INFLUX_ORG)

    for table in tables:
        for record in table.records:
            return record.get_value() or 0.0

    return 0.0


def _query_meter_peak_power_for_day(query_api, bucket, site_id, meter_id, start, end):
    """
    Internal: max active_power_total_kw for a meter over a specific IST day,
    and the timestamp it occurred at.
    Returns (peak_kw, peak_time) — (None, None) if no data in range.
    """
    flux = f'''import "math"

        from(bucket: "{bucket}")
            |> range(start: {start}, stop: {end})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => r.device == "{meter_id}")
            |> filter(fn: (r) => r._field == "active_power_total_kw")
            |> map(fn: (r) => ({{r with _value: math.abs(x: float(v: r._value))}}))
            |> top(n: 1)
        '''

    tables = query_api.query(flux, org=INFLUX_ORG)

    for table in tables:
        for record in table.records:
            return round(abs(record.get_value()), 2), record.get_time()

    return None, None


def _query_inverter_daily_sum_for_day(query_api, bucket, site_id, inverter_ids, start, end):
    """
    Internal: sum of each inverter's own energy_daily_kwh for the given IST day.

    NOTE: uses max(), not last(). energy_daily_kwh is an accumulator that rises
    through the generation day and then drops to 0 when the inverter shuts down
    at sunset (and/or resets at its internal midnight). last() therefore reads a
    sleeping inverter and returns 0.0. The day's total is the peak the counter
    reached, not its value at 23:59.

    Cross-check figure only — not the authoritative daily energy (that's the
    meter). Expect this to run slightly ABOVE meter export, since it's measured
    at the inverter AC terminals, before transformer/cable losses.

    Returns (total_kwh, count_reporting).
    """
    device_filter = ' or '.join(f'r.device == "{d}"' for d in inverter_ids)

    flux = f'''
        from(bucket: "{bucket}")
            |> range(start: {start}, stop: {end})
            |> filter(fn: (r) => r._measurement == "solar_data")
            |> filter(fn: (r) => r.site == "{site_id}")
            |> filter(fn: (r) => {device_filter})
            |> filter(fn: (r) => r._field == "energy_daily_kwh")
            |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
            |> max()
    '''

    tables = query_api.query(flux, org=INFLUX_ORG)
    total = 0.0
    count = 0

    for table in tables:
        for record in table.records:
            value = record.get_value()
            if value is None:
                continue
            total += abs(value)
            count += 1

    return round(total, 3), count