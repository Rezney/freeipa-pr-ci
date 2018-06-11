import os
import re
import boto3
from jinja2 import Template
from datetime import datetime

from .common import PopenTask, TaskException, FallibleTask
from .constants import (CLOUD_JOBS_DIR, CLOUD_JOBS_URL, CLOUD_URL,
                        CLOUD_BUCKET, UUID_RE, JOBS_DIR, TASKS_DIR)


"""
Previously we were updating test results in Fedora infra where the results were
directly served as part of web server directory listing capabilities. This is
not case of AWS S3.
In order to simulate same environment we are generating "index.html" using
Jinja2 template and putting it into every directory. Then we upload every file
and directory using boto3 library. Before upload we also set correct
"ContentEncoding" and "ContentType" so files (.gz, .png) are directly served.
At the end we create root jobs index to list all jobs in the bucket.
"""


def create_root_jobs_index():
    """
    Generate root jobs index using boto3 client. Pagination is needed as S3
    returns only 1000 objects at once.
    """
    client = boto3.client('s3')
    paginator = client.get_paginator('list_objects_v2')
    objects = []
    iterator = paginator.paginate(Bucket=CLOUD_BUCKET, Prefix=CLOUD_JOBS_DIR,
                                  Delimiter='/', PaginationConfig={'PageSize': None})
    for job_uuid in iterator.search('CommonPrefixes'):
        job_dir = job_uuid['Prefix']
        job = client.get_object(Bucket=CLOUD_BUCKET, Key=job_dir)
        name = job_dir.split(os.sep)[-2]
        mtime_obj = job['LastModified']
        mtime = mtime_obj.strftime('%c')
        size = '4096'
        type = 'dir'
        objects.append({'name': name,
                        'mtime': mtime,
                        'size': size,
                        'type': type})

    obj_data = {'objects': objects}

    client.put_object(Body=generate_index(obj_data, is_root=True),
                      Bucket=CLOUD_BUCKET, Key=CLOUD_JOBS_DIR+'index.html',
                      ContentEncoding='utf-8', ContentType='text/html')

def generate_index(obj_data, is_root=False):
    """
    Generate Jinja2 template for index.html with all AWS S3 objects
    (files and directories).
    For jobs index we use different template.
    """

    jinja_ctx = {'obj_data': obj_data, 'cloud_jobs_url': CLOUD_JOBS_URL,
        'cloud_url': CLOUD_URL,}

    if is_root:
        template = 'root_index_template.html'
    else:
        template = 'index_template.html'

    with open(os.path.join(TASKS_DIR, template), 'r') as file_:
        template = Template(file_.read())
    return template.render(jinja_ctx)


def write_index(obj_data, path):
    """
    Write index.html into every directory (locally).
    """
    index_loc = os.path.join(path, 'index.html')
    with open(index_loc, 'w') as fd:
        fd.write(generate_index(obj_data))


def create_local_indeces(uuid):
    """
    Go through whole job result directory structure and gather all files with
    metadata for every directory. Note: AWS S3 does not support classic web
    server browseability capabilities so we do this in order to avoid
    JavaScript solution on storage side. Also there is no concept of
    files/directories but rather objects. In this case it is more convenient
    to do this locally.
    """
    job_dir = os.path.join(JOBS_DIR, uuid)
    job_path_start = job_dir.rfind(os.sep) + 1
    for root, dirs, files in os.walk(job_dir):
        objects = []
        for obj in dirs+files:
            m_time_epoch = os.stat(os.path.join(root,obj)).st_mtime
            mtime = datetime.fromtimestamp(m_time_epoch).strftime('%c')
            size = os.stat(os.path.join(root,obj)).st_size
            type = 'dir' if os.path.isdir(os.path.join(root,obj)) else 'file'
            objects.append({'name': obj,
                            'mtime': mtime,
                            'size': size,
                            'type': type})
        remote_path = root[job_path_start:]
        obj_data = {'remote_path': remote_path,
                    'uuid': uuid, 'objects': objects}
        write_index(obj_data, root)
        del objects


def open_file(path):
    with open(path, 'rb') as file_:
        return file_.read()


def create_s3_obj(loc_path, key):
    """
    Create S3 object of particular file/directory. Use proper encoding for
    different files.
    """
    client = boto3.client('s3')
    content_params = {}

    if os.path.isdir(loc_path):
        # we use empty Body and slash at the end to create "directory" on S3
        body = ''
        key = key+'/'
    else:
        body = open_file(loc_path)
        if key.endswith('.gz'):
            content_params.update({'ContentEncoding': 'gzip'})
        if key.endswith(('.html')):
            content_params.update({'ContentType': 'text/html'})
        elif key.endswith(('.png')):
            content_params.update({'ContentType': 'image/png'})
        else:
            content_params.update({'ContentType': 'text/plain'})

    client.put_object(Body=body,
                      Bucket=CLOUD_BUCKET,
                      Key=CLOUD_JOBS_DIR+key,
                      **content_params)


def upload_to_s3(uuid):
    """
    Upload content of job directory in S3
    """
    job_dir = os.path.join(JOBS_DIR, uuid)
    job_path_start = job_dir.rfind(os.sep) + 1
    # create UUID directory just once
    create_s3_obj(job_dir, uuid)
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


class CloudUpload(FallibleTask):
    def __init__(self, uuid, **kwargs):
        if not re.match(UUID_RE, uuid):
            raise TaskException(self, "Invalid job UUID")
        super(CloudUpload, self).__init__(**kwargs)
        self.uuid = uuid
    
    def _run(self):
        create_local_indeces(self.uuid)
        upload_to_s3(self.uuid)
        create_root_jobs_index()
