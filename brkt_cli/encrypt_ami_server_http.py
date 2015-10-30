# Copyright 2015 Bracket Computing, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# https://github.com/brkt/brkt-sdk-java/blob/master/LICENSE
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and
# limitations under the License.

import json
import ssl
import time
from wsgiref.simple_server import make_server

import boto
import boto.dynamodb2
import boto.sqs
import boto.sqs.jsonmessage
from boto.dynamodb2.table import Table

from flask import Flask, request, make_response
app = Flask(__name__)


def build_job(item):
    return {
        'encrypt_id': item['encrypt_id'],
        'region': item['region'],
        'ami': item['ami'],
        'encryptor_ami': item['encryptor_ami'],
        'encrypted_ami_name': item['encrypted_ami_name'],
        'role': item['role'],
        'status': item['status'],
        'start_time': time.ctime(item['start_time']),
        'complete_time': (
            time.ctime(item['complete_time'])
            if item['complete_time'] else None),
        'log': item['log']
    }


@app.route("/encrypt/<cust_id>/<encrypt_id>")
def poll(cust_id, encrypt_id):
    db_conn = boto.dynamodb2.connect_to_region(app.config['REGION'])
    jobs = Table(app.config['TABLE_NAME'], connection=db_conn)
    try:
        item = jobs.get_item(encrypt_id=encrypt_id)
    except boto.dynamodb2.exceptions.ItemNotFound:
        return make_response(
            'job not found (not ready yet), try again later', 404)
    return json.dumps(build_job(item), indent=4)


@app.route("/encrypt/<cust_id>")
def jobs(cust_id):
    db_conn = boto.dynamodb2.connect_to_region(app.config['REGION'])
    jobs = Table(app.config['TABLE_NAME'], connection=db_conn)

    end_time = int(time.time()) + 3600  # 10 minutes of buffer

    items = jobs.query_2(
        index='customer_id-complete_time-index',
        complete_time__lt=end_time,
        customer_id__eq=cust_id,
        query_filter={
            'stats__ne': 'DELETED'
        }
    )
    jobs = []
    for item in items:
        jobs.append(build_job(item))
    return json.dumps(jobs, indent=4)


@app.route("/encrypt/<cust_id>", methods=['POST'])
def encrypt(cust_id):
    job = json.loads(request.data)
    job['customer_id'] = cust_id

    app.config['QUEUE'].put(job)
    return json.dumps(job, indent=4)


def make_http_server(values, queue):
    app.config['REGION'] = values.region
    app.config['QUEUE'] = queue
    app.config['TABLE_NAME'] = values.table_name
    httpd = make_server('', values.port, app)
    if values.cert:
        httpd.socket = ssl.wrap_socket(
            httpd.socket,
            certfile=values.cert,
            keyfile=values.key,
            server_side=True)
    return httpd
