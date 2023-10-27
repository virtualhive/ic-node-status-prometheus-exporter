#!/usr/bin/python3

import time
import requests
import logging
import os
from prometheus_client import start_http_server, Gauge, REGISTRY, PROCESS_COLLECTOR, PLATFORM_COLLECTOR, GC_COLLECTOR

NODE_PROVIDER_ID = None
EXPORTER_PORT = 8000

NODE_STATUS_LABEL_NAMES = ['node_id','node_operator_id','node_provider_id','node_provider_name','owner','region','subnet_id','ip_address','dc_id','dc_name']
API_ERROR_FLAG = False

def read_config():
    global EXPORTER_PORT
    global NODE_PROVIDER_ID
    if os.path.isfile('.env'):
        with open('.env') as env_file:
            logging.info('Found .env file!')
            for line in env_file:
                key_value_pair = line.rstrip()
                if key_value_pair.startswith('EXPORTER_PORT'):
                    EXPORTER_PORT = int(key_value_pair.split('=')[1])
                    logging.info(f'Found EXPORTER_PORT in .env file ({EXPORTER_PORT})')
                if key_value_pair.startswith('NODE_PROVIDER_ID'):
                    NODE_PROVIDER_ID = key_value_pair.split('=')[1]
                    logging.info(f'Read NODE_PROVIDER_ID in .env file ({NODE_PROVIDER_ID})')
    exporter_port_envvar = os.getenv('EXPORTER_PORT')
    if exporter_port_envvar is not None:
        EXPORTER_PORT = exporter_port_envvar
        logging.info(f'Found env var EXPORTER_PORT ({exporter_port_envvar})')
    node_provider_id_envvar = os.getenv('NODE_PROVIDER_ID')
    if node_provider_id_envvar is not None:
        NODE_PROVIDER_ID = node_provider_id_envvar
        logging.info(f'Found env var NODE_PROVIDER_ID ({node_provider_id_envvar})')
    
    if NODE_PROVIDER_ID is None:
        logging.error('Could not find NODE_PROVIDER_ID value. Please specify it in your .env file or set up an environment variable.\nExiting...')
        exit(1)


def get_data_from_ic_api():
    global API_ERROR_FLAG
    try:
        headers = {
            'User-Agent': 'IC Node Status Prometheus Exporter (github.com/virtualhive/ic-node-status-prometheus-exporter)',
        }
        r = requests.get(f"https://ic-api.internetcomputer.org/api/v3/nodes?node_provider_id={NODE_PROVIDER_ID}", headers=headers)
        if r.ok:
            json_content = r.json()
        else:
            logging.error('IC API response error! Status Code: %s, Error:\n%s' % (r.status_code, r.text))
            json_content = None
            API_ERROR_FLAG = True
    except Exception as ex:
        logging.error('IC API request error! Error:\n%s' % ex)
        json_content = None
        API_ERROR_FLAG = True
    return json_content

def map_status(status):
    if status == "UP":
        return 1
    elif status == "UNASSIGNED":
        return 2
    elif status == "DEGRADED":
        return 3
    elif status == "DOWN":
        return 4
    elif status == "UNRECOGNIZED":
        return 5
    else:
        return 0

def init_metrics():
    logging.info(f"Initializing metrics for node provider ID: {NODE_PROVIDER_ID}...")

    REGISTRY.unregister(PROCESS_COLLECTOR)
    REGISTRY.unregister(PLATFORM_COLLECTOR)
    REGISTRY.unregister(GC_COLLECTOR)

    metrics = {}
    metrics['ic_node_api_up'] = Gauge('ic_node_api_up', 'Status of the IC API')
    metrics['ic_node_count'] = Gauge('ic_node_count', 'Number of nodes found for the given node provider ID', ['node_provider_id'])
    metrics['ic_node_status'] = Gauge('ic_node_status', 'Numerical encoded status of the IC node', NODE_STATUS_LABEL_NAMES)
    return metrics

def update_metrics(metrics):
    json_data = get_data_from_ic_api()
    if json_data is None:
        metrics['ic_node_api_up'].set(0)
        metrics['ic_node_count'].labels(node_provider_id=NODE_PROVIDER_ID).set(0)
        metrics['ic_node_status'].clear()
    else:
        global API_ERROR_FLAG
        if API_ERROR_FLAG:
            API_ERROR_FLAG = False
            logging.info('IC API is online. Continuing scraping...')
        metrics['ic_node_api_up'].set(1)
        metrics['ic_node_count'].labels(node_provider_id=NODE_PROVIDER_ID).set(len(json_data['nodes']))

        metrics['ic_node_status'].clear()
        for i in range(0, len(json_data['nodes'])):
            node_data = json_data['nodes'][i]
            metrics['ic_node_status'].labels(
                node_id=node_data['node_id'],
                node_operator_id=node_data['node_operator_id'],
                node_provider_id=node_data['node_provider_id'],
                node_provider_name=node_data['node_provider_name'],
                owner=node_data['owner'],
                region=node_data['region'],
                subnet_id=node_data['subnet_id'],
                ip_address=node_data['ip_address'],
                dc_id=node_data['dc_id'],
                dc_name=node_data['dc_name']
            ).set(map_status(node_data['status']))


if __name__ == "__main__":
    FORMAT = '%(asctime)s | %(levelname)s | %(message)s'
    logging.basicConfig(format=FORMAT, level=logging.INFO)

    read_config()
    metrics = init_metrics()

    start_http_server(EXPORTER_PORT)
    logging.info(f"Started IC node status Prometheus exporter on port {EXPORTER_PORT}")
    logging.info("Scraping...")
    while(True):
        update_metrics(metrics)
        time.sleep(60)
