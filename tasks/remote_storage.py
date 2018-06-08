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
    iterator = paginator.paginate(Bucket=CLOUD_BUCKET, Prefix='jobs/', Delimiter='/', PaginationConfig={'PageSize': None})
    for job_dir in iterator.search('CommonPrefixes'):
        job_id = job_dir.get('Prefix')
        for job in client.list_objects(Bucket=CLOUD_BUCKET, Prefix=job_id, Delimiter='/')['Contents']:
            name = job['Key'].split(os.sep)[-2]
            mtime_obj = job['LastModified']
            mtime = mtime_obj.strftime('%c')
            size = job['Size']
            type = 'dir'
            objects.append({'name': name,
                            'mtime': mtime,
                            'size': size,
                            'type': type})

    client.put_object(Body=generate_index(objects), Bucket=CLOUD_BUCKET,
                      Key=CLOUD_JOBS_DIR+'index.html', ContentEncoding='utf-8')


def generate_index(obj_data):
    """
    Generate Jinja2 template with all AWS S3 objects (files and directories)
    """
    with open(os.path.join(TASKS_DIR, 'upload_artifacts.html'), 'r') as file_:
        template = Template(file_.read())
    return template.render(
        {'tree': obj_data, 'cloud_jobs_url': CLOUD_JOBS_URL,
         'cloud_url': CLOUD_URL})


def write_index(obj_data):
    """
    Write index.html into every directory.
    """
    index_loc = os.path.join(obj_data['local_path'], 'index.html')
    with open(index_loc, 'w') as fd:
        fd.write(generate_index(obj_data))


def create_local_indeces(job_dir):
    """
    Go through whole job result directory structure and gather all files with
    metadata for every directory. Note: AWS S3 does not support classic web
    server browseability capabilities so we do this in order to avoid
    JavaScript on storage side.
    """
    job_dir_start = job_dir.rfind(os.sep) + 1
    uuid = job_dir.split(os.sep)[-1]
    for path, dirs, files in os.walk(job_dir):
        objects = []
        if path != job_dir:
            prev_path = '/'.join(path[job_dir_start:].split(os.sep)[:-1])
            objects.append({'name': 'Parent directory', 'type': 'parent_link',
                            'prev_path': prev_path})
        for obj in dirs+files:
            m_time_epoch = os.stat(os.path.join(path,obj)).st_mtime
            mtime = datetime.fromtimestamp(m_time_epoch).strftime('%c')
            size = os.stat(os.path.join(path,obj)).st_size
            type = 'dir' if os.path.isdir(os.path.join(path,obj)) else 'file'
            objects.append({'name': obj,
                            'mtime': mtime,
                            'size': size,
                            'type': type})
        dest_path = path[job_dir_start:]
        obj_data = {'local_path': path, 'remote_path': dest_path, 'uuid': uuid,
                  'objects': objects}
        write_index(obj_data)
        del objects


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


class CloudSyncTask(PopenTask):
    def __init__(self, src, dest, extra_args=None, **kwargs):
        if extra_args is None:
            extra_args = []

        cmd = [
            'aws',
            's3',
            'sync',
            src,
            dest,
        ]
        cmd + extra_args

        super(CloudSyncTask, self).__init__(cmd, **kwargs)


class CloudUpload(CloudSyncTask):
    def __init__(self, uuid, **kwargs):
        if not re.match(UUID_RE, uuid):
            raise TaskException(self, "Invalid job UUID")

        create_local_indeces(os.path.join(JOBS_DIR, uuid))

        super(CloudUpload, self).__init__(
            os.path.join(JOBS_DIR, uuid),
            os.path.join(CLOUD_DIR, CLOUD_JOBS_DIR, uuid),
            **kwargs
        )

        create_jobs_index()
