# apps/reports/aggregation.py
#
# Read-time monthly/range aggregation over DailySiteSnapshot.
# Pure Postgres read — no InfluxDB, no polling cost. The report is only as
# rich as the nightly snapshot; this layer never re-derives from Influx.
#
# Null discipline (inherited from the snapshot): null means "not trustworthy /
# not applicable", never a fake 0.0. Sums skip nulls; averages divide by the
# non-null day count only; a capacity-normalized KPI is null when the site's
# dc_capacity_kw is null. A dead-meter day and a real zero day stay distinct.


from .models import DailySiteSnapshot


def _f(v):
    """Decimal/None -> float/None. Matches the float shape the influx views emit."""
    return float(v) if v is not None else None


def _utc_iso(dt):
    """Aware UTC datetime -> ISO-8601 string, or None. Frontend localizes to IST."""
    return dt.isoformat() if dt else None


def build_site_report(site, start_date, end_date):
    """
    site       : a Site instance (already tenant-resolved by the view)
    start_date : datetime.date (inclusive)
    end_date   : datetime.date (inclusive)
    Returns range meta + daily[] table. Summary/capacity intentionally omitted —
    the page is the per-day table only.
    """
    rows = list(
        DailySiteSnapshot.objects
        .filter(site=site, date__gte=start_date, date__lte=end_date)
        .order_by('date')
    )

    dc_cap = float(site.dc_capacity_kw) if site.dc_capacity_kw else None

    daily = []
    days_with_data = 0

    for r in rows:
        energy  = _f(r.energy_today_kwh)
        inv_sum = _f(r.energy_today_inverter_sum_kwh)
        pr      = _f(r.performance_ratio_pct)
        cuf     = _f(r.cuf_pct)
        poa     = _f(r.poa_irradiation_kwh_m2)
        co2     = _f(r.co2_avoided_kg)
        peak    = _f(r.peak_power_kw)

        specific_yield = (
            round(energy / dc_cap, 2) if (energy is not None and dc_cap) else None
        )

        gen_hours = None
        if r.generation_start_time and r.generation_end_time:
            gen_hours = round(
                (r.generation_end_time - r.generation_start_time).total_seconds() / 3600.0, 2
            )

        if energy is not None:
            days_with_data += 1

        daily.append({
            'date':                    r.date.isoformat(),
            'energy_kwh':              round(energy, 2) if energy is not None else None,
            'inverter_sum_kwh':        round(inv_sum, 2) if inv_sum is not None else None,
            'specific_yield_kwh_kwp':  specific_yield,
            'performance_ratio_pct':   pr,
            'cuf_pct':                 cuf,
            'peak_power_kw':           peak,
            'peak_power_time':         _utc_iso(r.peak_power_time),
            'generation_start_time':   _utc_iso(r.generation_start_time),
            'generation_end_time':     _utc_iso(r.generation_end_time),
            'generation_hours':        gen_hours,
            'poa_irradiation_kwh_m2':  round(poa, 3) if poa is not None else None,
            'co2_avoided_kg':          co2,
            'meter_status':            r.meter_status,
            'inverters_online_count':  r.inverters_online_count,
            'inverters_total_count':   r.inverters_total_count,
        })

    data_current_through = rows[-1].date.isoformat() if rows else None

    return {
        'range': {
            'start':                start_date.isoformat(),
            'end':                  end_date.isoformat(),
            'days':                 (end_date - start_date).days + 1,
            'days_with_data':       days_with_data,
            'data_current_through': data_current_through,
        },
        'daily': daily,
    }