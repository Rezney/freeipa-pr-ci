import os
import re
import boto3
from jinja2 import Template
from datetime import datetime

from .common import PopenTask, TaskException
from .constants import (CLOUD_DIR, CLOUD_JOBS_DIR, CLOUD_JOBS_URL, CLOUD_URL,
                        CLOUD_BUCKET, UUID_RE, JOBS_DIR, TASKS_DIR)


def create_jobs_index():
    """
    We generate jobs index usin
    """
    client = boto3.client('s3')
    paginator = client.get_paginator('list_objects_v2')
    objects = []
    iterator = paginator.paginate(Bucket=CLOUD_BUCKET, Prefix=CLOUD_JOBS_DIR,
                                  Delimiter='/',
                                  PaginationConfig={'PageSize': None})
    for job_dir in iterator.search('CommonPrefixes'):
        job_id = job_dir.get('Prefix')
        for job in client.list_objects(Bucket=CLOUD_BUCKET,
                                       Prefix=job_id,
                                       Delimiter='/')['Contents']:
            name = job['Key'].split(os.sep)[-2]
            mtime_obj = job['LastModified']
            mtime = mtime_obj.strftime('%c')
            size = job['Size']
            type = 'dir'
            objects.append({'name': name,
                            'mtime': mtime,
                            'size': size,
                            'type': type})

    obj_data = {'remote_path': CLOUD_URL+CLOUD_JOBS_DIR, 'objects': objects}

    client.put_object(Body=generate_index(obj_data, is_root=True),
                      Bucket=CLOUD_BUCKET, Key=CLOUD_JOBS_DIR+'index.html',
                      ContentEncoding='utf-8', ContentType='text/plain')


def generate_index(obj_data, is_root=False):
    """
    Generate Jinja2 template with all AWS S3 objects (files and directories)
    """

    jinja_ctx = {'obj_data': obj_data, 'cloud_jobs_url': CLOUD_JOBS_URL,
        'cloud_url': CLOUD_URL,}

    if is_root:
        jinja_ctx.update({'is_root': True})

    with open(os.path.join(TASKS_DIR, 'upload_artifacts.html'), 'r') as file_:
        template = Template(file_.read())
    return template.render(jinja_ctx)


def open_file(path):
    with open(path, 'rb') as file_:
        return file_.read()


def create_s3_obj(loc_path, key):
    client = boto3.client('s3')

    if os.path.isdir(loc_path):
        body = ''
        content_type = 'text/plain'
        key = key+'/'
    else:
        body = open_file(loc_path)
        if key.endswith('.gz'):
            content_type='text/plain'
        else:
            content_type='text/plain'
    client.put_object(Body=body,
                      Bucket='freeipa-org-pr-ci', Key='jobs/'+key,
                      ContentEncoding='utf-8', ContentType=content_type)


def upload_to_s3(uuid):
    job_dir = os.path.join(JOBS_DIR, uuid)
    job_path_start = job_dir.rfind(os.sep) + 1
    for root, dirs, files in os.walk(job_dir):
        key_rel_path = root[job_path_start:]
        for obj in dirs+files:
            create_s3_obj(os.path.join(root, obj),
                          os.path.join(key_rel_path, obj),
                          )


class GzipLogFiles(PopenTask):
    def __init__(self, directory, **kwargs):
        super(GzipLogFiles, self).__init__(self, **kwargs)
        self.directory = directory
        self.cmd = (
            'find {directory} '
            '-type f '
            '! -path "*/.vagrant/*" '
            '-a ! -path "*/assets/*" '
            '-a ! -path "*/rpms/*" '
            '-a ! -name "*.gz" '
            '-a ! -name "*.png" '
            '-a ! -name "Vagrantfile" '
            '-a ! -name "ipa-test-config.yaml" '
            '-a ! -name "vars.yml" '
            '-a ! -name "ansible.cfg" '
            '-a ! -name "report.html" '
            '-exec gzip "{{}}" \;'
        ).format(directory=directory)
        self.shell = True


class CloudUpload():
    def __init__(self, uuid, **kwargs):
        if not re.match(UUID_RE, uuid):
            raise TaskException(self, "Invalid job UUID")

        upload_to_s3(uuid)

