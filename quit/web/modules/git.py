import re
import pygit2

from flask import Blueprint, flash, redirect, request, url_for, current_app
from quit.web.app import render_template
from quit.web.commits_graph import CommitGraph, generate_graph_data

import sys, traceback

__all__ = [ 'git' ]

git = Blueprint('git', __name__)

@git.route("/commits", defaults={'branch_or_ref': None}, methods=['GET'])
@git.route("/commits/<branch_or_ref>", methods=['GET'])
def commits(branch_or_ref):
    """
    Lists all commits of a given git branch.

    Returns:
        HTTP Response with commits.
    """
    if not branch_or_ref:
        branch_or_ref= 'master'

    quit = current_app.config['quit']

    try:
        results = quit.repository.revisions(branch_or_ref, order=pygit2.GIT_SORT_TIME)
        data = generate_graph_data(CommitGraph.gets(results))

        return render_template('commits.html', results=results, data=data)
    except Exception as e:
        current_app.logger.error(e)
        current_app.logger.error(traceback.format_exc())
        return "<pre>"+traceback.format_exc()+"</pre>", 403

@git.route("/pull", methods=['POST', 'GET'])
def pull():
    """Pull from remote.

    Returns:
        HTTP Response 201: If pull was possible
        HTTP Response: 403: If pull did not work
    """
    #if current_app.config['repository'].pull():
    #    return '', status.HTTP_201_CREATED
    #else:
    #    return '', status.HTTP_403_FORBIDDEN
    try:
        quit = current_app.config['quit']
        quit.repository.pull()
        return '', 201
    except Exception as e:
        current_app.logger.error(e)
        current_app.logger.error(traceback.format_exc())
        return "<pre>"+traceback.format_exc()+"</pre>", 403

@git.route("/push", methods=['POST', 'GET'])
def push():
    """Pull from remote.

    Returns:
        HTTP Response 201: If push was possible
        HTTP Response: 403: If push did not work
    """
    #if current_app.config['repository'].push():
    #    return '', status.HTTP_201_CREATED
    #else:
    #    return '', status.HTTP_403_FORBIDDEN

    try:
        quit = current_app.config['quit']
        quit.repository.push()
        return '', 201
    except Exception as e:
        current_app.logger.error(e)
        current_app.logger.error(traceback.format_exc())
        return "<pre>"+traceback.format_exc()+"</pre>", 403
