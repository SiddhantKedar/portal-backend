# apps/influx/client.py
# Manages the InfluxDB connection.
# One single connection is created and reused across all queries.
# This file is the only place in the entire project that
# knows about InfluxDB connection details.

import os
from influxdb_client import InfluxDBClient
from dotenv import load_dotenv

load_dotenv()

# Read credentials from .env
INFLUX_URL   = os.getenv('INFLUX_URL')
INFLUX_TOKEN = os.getenv('INFLUX_TOKEN')
INFLUX_ORG   = os.getenv('INFLUX_ORG')


def get_influx_client():
    """
    Returns an InfluxDB client instance.
    Usage:
        client = get_influx_client()
        query_api = client.query_api()
    Always close the client after use or use it as a context manager.
    """
    return InfluxDBClient(
        url=INFLUX_URL,
        token=INFLUX_TOKEN,
        org=INFLUX_ORG
    )


def test_connection():
    """
    Quick check to verify InfluxDB is reachable.
    Returns True if connected, False if not.
    """
    try:
        client = get_influx_client()
        health = client.health()
        client.close()
        return health.status == 'pass'
    except Exception as e:
        print(f'InfluxDB connection failed: {e}')
        return False