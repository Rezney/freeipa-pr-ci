#!/usr/bin/python3

import os
import github3
import argparse
import logging
import yaml
from cachecontrol.adapter import CacheControlAdapter
import git
from git import Repo


REF_FORMAT = 'refs/heads/'
DEFAULT_COMMIT_MSG = 'automated commit'
FREEIPA_PRCI_CONFIG_FILE = '.freeipa-pr-ci.yaml'
PRCI_DEF_DIR = 'ipatests/prci_definitions'
REMOTE_REPO = 'https://github.com/freeipa/freeipa.git'
UPSTREAM_REMOTE_REF = 'upstream'
MYGITHUB_REMOTE_REF = 'mygithub'
BOX_TEMPL_NAME = 'ci-{{branch}}-f{{fedora_version}}'
BOX_TEMPL_NAME_RE =

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
consoleHandler = logging.StreamHandler()
consoleHandler.setLevel(logging.DEBUG)
logger.addHandler(consoleHandler)


def load_yaml(yml_path):
    try:
        with open(yml_path) as yml_file:
            return yaml.load(yml_file)
    except IOError as exc:
        raise argparse.ArgumentTypeError(
            'Failed to open {}: {}'.format(yml_path, exc))
    except yaml.YAMLError as exc:
        raise argparse.ArgumentTypeError(
            'Failed to parse YAML from {}: {}'.format(yml_path, exc))


class AutomatedPR(object):

    def __init__(self, github_token, repo, args):
        github = github3.login(token=github_token)
        github.session.mount('https://api.github.com', CacheControlAdapter())
        self.repo = github.repository(repo['owner'], repo['name'])
        self.upstream_repo = github.repository('freeipa', 'freeipa')
        self.args = args

    def commit_new_prci_config_file(self):
        """
        Updates the .freeipa-pr-ci.yaml file with the content
        of the --prci_config provided file.
        """
        repo = Repo(self.args.repo_path)

        self.delete_local_branch()

        # creates new branch using the identifier as the name
        repo.git.checkout('-b', self.args.id)

        current_prci_test_config = os.path.join(self.args.repo_path,
                                        FREEIPA_PRCI_CONFIG_FILE)

        # changing the file that FREEIPA_PRCI_CONFIG_FILE points to
        os.unlink(current_prci_test_config)
        os.symlink(self.args.prci_config, current_prci_test_config)

        repo.git.add(FREEIPA_PRCI_CONFIG_FILE)
        repo.git.commit('-m', DEFAULT_COMMIT_MSG)
        repo.git.push("-u", MYGITHUB_REMOTE_REF, self.args.id)

    def bump_prci_version(self, templ_name, templ_ver):
        for r, d, f in os.walk(os.path.join(self.arg.repo_path, PRCI_DEF_DIR)):
            file = os.path.join(r, f)
            yaml_text = load_yaml(file)
            templ_name_re =


    def close_older_pr(self):
        refs = {r.ref: r for r in self.repo.refs()}
        ref_uri = '{}{}'.format(REF_FORMAT, self.args.id)
        try:
            ref = refs[ref_uri]
            ref.delete()
            logger.debug("Branch %s deleted", self.args.id)
        except KeyError:
            pass

    def rebase_branch(self):
        repo = Repo(self.args.repo_path)

        try:
            repo.git.remote('add', UPSTREAM_REMOTE_REF, REMOTE_REPO)
        except git.exc.GitCommandError:
            # the remote is already configured
            pass

        repo.git.fetch(UPSTREAM_REMOTE_REF)
        repo.git.checkout(self.args.branch)
        repo.git.pull(UPSTREAM_REMOTE_REF, self.args.branch)
        repo.git.push(MYGITHUB_REMOTE_REF, self.args.branch)

    def delete_local_branch(self):
        repo = Repo(self.args.repo_path)
        repo.git.checkout(self.args.branch)
        try:
            repo.git.branch("-D", self.args.id)
        except:
            pass

    def nightly_pr(self):
        # before opening a new PR, we close the old one with the same
        # identifier. The PR list shoud have only one open PR.
        self.close_older_pr()
        self.rebase_branch()
        self.commit_new_prci_config_file()

        pr_title = '[{}] Nightly PR'.format(self.args.id)

        owner = ('freeipa' if self.args.pr_against_upstream
                 else self.repo.owner.login)
        logger.debug("A new PR against %s/freeipa will be created with "
                     "the title %s", owner, pr_title)
        self.open_pr(self, pr_title)
        self.delete_local_branch()

    def template_pr(self):
        pass

    def open_pr(self, pr_title):
        owner = ('freeipa' if self.args.pr_against_upstream
                 else self.repo.owner.login)
        logger.debug("A new PR against %s/freeipa will be created with "
                     "the title %s", owner, pr_title)

        try:
            if self.args.pr_against_upstream:
                users_head = '{}:{}'.format(self.repo.owner.login, self.args.id)
                pr = self.upstream_repo.create_pull(pr_title, self.args.branch,
                                                    users_head)
            else:
                # will open a PR against user's fork
                pr = self.repo.create_pull(pr_title, self.args.branch,
                                           self.args.id)

            logger.info("PR %s created", pr.number)
        except github3.GitHubError as error:
            logger.error(error.errors)

    def run(self, args):
        fnc = getattr(self, args.command)
        logger.debug('Executing %s command', args.command)
        return fnc(args)


def create_parser():
    parser = argparse.ArgumentParser(description='')

    parser.add_argument(
        '--branch', type=str, required=True,
        help='Branch name to open PR against it'
    )

    parser.add_argument(
        '--repo_path', type=str, required=True,
        help='freeIPA repo path'
    )

    commands = parser.add_subparsers(dest='command')

    nightly = commands.add_parser('open__nightly_pr',
                        description="Opens a PR for Nightly Tests")

    nightly.add_argument(
        '--config', type=config_file, required=True,
        help='YAML file with complete configuration.',
    )

    nightly.add_argument(
        '--prci_config', type=str, required=True,
        help="Relative path to PR CI test definition (yaml) file in "
             "FreeIPA repo. E.g: ipatests/prci_definitions/gating"
    )

    template = commands.add_parser('open_template_pr',
        description="Opens a PR for bumping PRCI template version")

    template.add_argument(
        '--prci_def_dir', type=str, required=True,
        help='PRCI definitions relative path in freeipa repo'
    )

    template.add_argument(
        '--branch', type=str, required=True,
        help='Branch name to open PR against'
    )

    template.add_argument(
        '--fedora_ver', type=int, required=True,
        help='Fedora version'
    )


    def __string_to_bool(value):
        if value.lower() in ['yes', 'true', 't', 'y', '1']:
            return True
        elif value.lower() in ['no', 'false', 'f', 'n', '0']:
            return False
        raise argparse.ArgumentTypeError('Boolean value expected.')

    parser.add_argument(
        '--pr_against_upstream', type=__string_to_bool, required=True,
        help="Should the PR be open against the upstream repo? Use False for "
             "opening against your own freeipa repo"
    )

    return parser


def config_file(path):
    config = load_yaml(path)

    fields_required = ['repository', 'credentials']
    for field in fields_required:
        if field not in config:
            raise argparse.ArgumentTypeError(
                'Missing required section {} in config file', field)
    return config


def main():
    parser = create_parser()
    args = parser.parse_args()

    config = args.config
    creds = config['credentials']
    repository = config['repository']

    logger.debug('Running Open and Close PR Tool against %s/%s repo',
                 repository['owner'], repository['name'])

    automated_pr = AutomatedPR(creds['token'], repository, args)
    automated_pr.run()


if __name__ == '__main__':
    main()
