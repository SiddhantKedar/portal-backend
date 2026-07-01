# apps/influx/metrics.py
# Whitelist of fields exposed on the Analytics page.
# Maps a safe, user-facing metric key to the real InfluxDB field name per
# device type, since inverters and meters use different field names for
# the same concept (except frequency). Only metrics listed here are
# queryable — this is the actual security boundary, not the frontend.

ANALYTICS_METRICS = {
    'active_power': {
        'label': 'Active Power', 'unit': 'kW',
        'fields': {'INVERTER': 'ac_active_power_kw', 'METER': 'active_power_total_kw'},
    },
    'reactive_power': {
        'label': 'Reactive Power', 'unit': 'kVAR',
        'fields': {'INVERTER': 'ac_reactive_power_kvar', 'METER': 'reactive_power_total_kvar'},
    },
    'power_factor': {
        'label': 'Power Factor', 'unit': '',
        'fields': {'INVERTER': 'ac_power_factor', 'METER': 'power_factor_total'},
    },
    'grid_frequency': {
        'label': 'Grid Frequency', 'unit': 'Hz',
        'fields': {'INVERTER': 'grid_frequency_hz', 'METER': 'grid_frequency_hz'},
    },
    'voltage_l1_l2': {
        'label': 'Voltage (L1-L2)', 'unit': 'V',
        'fields': {'INVERTER': 'grid_voltage_ab_v', 'METER': 'voltage_line_ab_v'},
    },
    'voltage_l2_l3': {
        'label': 'Voltage (L2-L3)', 'unit': 'V',
        'fields': {'INVERTER': 'grid_voltage_bc_v', 'METER': 'voltage_line_bc_v'},
    },
    'voltage_l3_l1': {
        'label': 'Voltage (L3-L1)', 'unit': 'V',
        'fields': {'INVERTER': 'grid_voltage_ca_v', 'METER': 'voltage_line_ca_v'},
    },
    'current_phase_a': {
        'label': 'Current (Phase A)', 'unit': 'A',
        'fields': {'INVERTER': 'ac_current_phase_a', 'METER': 'current_phase_a'},
    },
    'current_phase_b': {
        'label': 'Current (Phase B)', 'unit': 'A',
        'fields': {'INVERTER': 'ac_current_phase_b', 'METER': 'current_phase_b'},
    },
    'current_phase_c': {
        'label': 'Current (Phase C)', 'unit': 'A',
        'fields': {'INVERTER': 'ac_current_phase_c', 'METER': 'current_phase_c'},
    },
    'inverter_efficiency': {
        'label': 'Inverter Efficiency', 'unit': '%',
        'fields': {'INVERTER': 'inverter_efficiency_pct'},
    },
    'dc_input_power': {
        'label': 'DC Input Power', 'unit': 'kW',
        'fields': {'INVERTER': 'dc_input_power_kw'},
    },
    'internal_temp': {
        'label': 'Internal Temperature', 'unit': '\u00b0C',
        'fields': {'INVERTER': 'internal_temp_c'},
    },
}