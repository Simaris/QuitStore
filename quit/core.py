import pygit2

from datetime import datetime
import logging
from os import makedirs, environ
from os.path import abspath, exists, isdir, isfile, join, expanduser
from quit.exceptions import QuitGitRepoError
from subprocess import Popen
from functools import lru_cache

import pygit2
from pygit2 import GIT_MERGE_ANALYSIS_UP_TO_DATE
from pygit2 import GIT_MERGE_ANALYSIS_FASTFORWARD
from pygit2 import GIT_MERGE_ANALYSIS_NORMAL
from pygit2 import GIT_SORT_REVERSE, GIT_RESET_HARD, GIT_STATUS_CURRENT
from pygit2 import init_repository, clone_repository
from pygit2 import Repository, Signature, RemoteCallbacks
from pygit2 import KeypairFromAgent, Keypair, UserPass
from pygit2 import credentials
from rdflib import ConjunctiveGraph, Graph, URIRef, BNode, Literal

from rdflib import plugin
from rdflib.store import Store as DefaultStore
from rdflib.graph import ReadOnlyGraphAggregate

from quit.conf import STORE_NONE, STORE_DATA, STORE_PROVENANCE, STORE_ALL
from quit.namespace import RDF, RDFS, FOAF, XSD, PROV, QUIT, is_a
from quit.graphs import ReadOnlyRewriteGraph, InMemoryGraphAggregate
from quit.utils import graphdiff

from subprocess import Popen

logger = logging.getLogger('quit.core')


class FileReference:
    """A class that manages n-quad files.

    This class stores inforamtation about the location of a n-quad file and is
    able to add and delete triples/quads to that file.
    """

    def __init__(self, filelocation, versioning=True):
        """Initialize a new FileReference instance.

        Args:
            filelocation: A string of the filepath.
            versioning: Boolean if versioning is enabled or not. (Defaults true)
            filecontentinmem: Boolean to decide if local filesystem should be used to
                or if file content should be kept in memory too . (Defaults false)

        Raises:
            ValueError: If no file at the filelocation, or in the given directory + filelocation.
        """
        logger = logging.getLogger('quit.core.FileReference')
        logger.debug('Create an instance of FileReference')
        self.content = None
        self.path = abspath(filelocation)
        self.modified = False

        return

    def __getcontent(self):
        """Return the content of a n-quad file.

        Returns:
            content: A list of strings where each string is a quad.
        """
        return self.content

    def __setcontent(self, content):
        """Set the content of a n-quad file.

        Args:
            content: A list of strings where each string is a quad.
        """
        self.content = content
        return

    def getgraphfromfile(self):
        """Return a Conjunctive Graph generated from the referenced file.

        Returns:
            A ConjunctiveGraph
        """
        graph = ConjunctiveGraph()

        try:
            graph.parse(self.path, format='nquads', publicID='http://localhost:5000/')
            logger.debug('Success: File', self.path, 'parsed')
        except KeyError as e:
            # Given file contains non valid rdf data
            # logger.debug('Error: File', self.path, 'not parsed')
            # self.__setcontent([[None][None][None][None]])
            pass

        return graph

    def getcontent(self):
        """Public method that returns the content of a nquad file.

        Returns:
            content: A list of strings where each string is a quad.
        """
        return self.__getcontent()

    def setcontent(self, content):
        """Public method to set the content of a n-quad file.

        Args:
            content: A list of strings where each string is a quad.
        """
        self.__setcontent(content)
        return

    def savefile(self):
        """Save the file."""
        f = open(self.path, "w")

        logger.debug('Saving file:', self.path)
        content = self.__getcontent()
        for line in content:
            f.write(line + '\n')
        f.close

        logger.debug('File saved')

    def sortcontent(self):
        """Order file content."""
        content = self.__getcontent()

        try:
            self.__setcontent(sorted(set(content)))
        except AttributeError:
            pass

    def addquads(self, quads):
        """Add quads to the file content."""
        self.content.append(quads)
        self.sortcontent()

        return

    def addquad(self, quad):
        """Add a quad to the file content."""

        self.content.append(quad)

    def deletequads(self, quads):
        """Remove quads from the file content."""
        for quad in quads:
            self.content.remove(quad)

        return True

    def deletequad(self, quad):
        """Remove a quad from the file content."""
        try:
            self.content.remove(quad)
            self.modified = True
        except ValueError:
            # not in list
            pass

        return

    def isversioned(self):
        """Check if a File is part of version control system."""
        return(self.versioning)


class Queryable:
    """
    A class that represents a querable graph-like object.
    """

    def __init__(self, **kwargs):
        self.store = ConjunctiveGraph(identifier='default')

    def query(self, querystring):
        """Execute a SPARQL select query.

        Args:
            querystring: A string containing a SPARQL ask or select query.
        Returns:
            The SPARQL result set
        """
        pass

    def update(self, querystring, versioning=True):
        """Execute a SPARQL update query and update the store.

        This method executes a SPARQL update query and updates and commits all affected files.

        Args:
            querystring: A string containing a SPARQL upate query.
        """
        pass


class Store(Queryable):
    """A class that combines and syncronieses n-quad files and an in-memory quad store.

    This class contains information about all graphs, their corresponding URIs and
    pathes in the file system. For every Graph (context of Quad-Store) exists a
    FileReference object (n-quad) that enables versioning (with git) and persistence.
    """

    def __init__(self, store):
        """Initialize a new MemoryStore instance."""
        logger = logging.getLogger('quit.core.MemoryStore')
        logger.debug('Create an instance of MemoryStore')
        self.store = store

        return

    def getgraphuris(self):
        """Method to get all available named graphs.

        Returns:
            A list containing all graph uris found in store.
        """
        graphs = []
        for graph in self.store.contexts():
            if isinstance(graph, BNode) or str(graph.identifier) == 'default':
                pass
            else:
                graphs.append(graph.identifier)

        return graphs

    def getgraphcontent(self, graphuri):
        """Get the serialized content of a named graph.

        Args:
            graphuri: The URI of a named graph.
        Returns:
            content: A list of strings where each string is a quad.
        """
        data = []
        context = self.store.get_context(URIRef(graphuri))
        triplestring = context.serialize(format='nt').decode('UTF-8')

        # Since we have triples here, we transform them to quads by adding the graphuri
        # TODO This might cause problems if ' .\n' will be part of a literal.
        #   Maybe a regex would be a better solution
        triplestring = triplestring.replace(' .\n', ' <' + graphuri + '> .\n')

        data = triplestring.splitlines()
        data.remove('')

        return data

    def getstoreobject(self):
        """Get the conjunctive graph object.

        Returns:
            graph: A list of strings where each string is a quad.
        """

    def graphexists(self, graphuri):
        """Ask if a named graph FileReference object for a named graph URI.

        Args:
            graphuri: A string containing the URI of a named graph

        Returns:
            True or False
        """
        if self.store.get_context(URIRef(graphuri)) is None:
            return False
        else:
            return True

    def addfile(self, filename, serialization):
        """Add a file to the store.

        Args:
            filename: A String for the path to the file.
            serialization: A String containg the RDF format
        Raises:
            ValueError if the given file can't be parsed as nquads.
        """
        try:
            self.store.parse(source=filename, format=serialization)
        except Exception as e:
            logger.debug(e)
            logger.debug(
                "Could not import file: {}. " +
                "Make sure the file exists and contains data in  {}".format(
                    filename,
                    serialization
                )
            )

    def addquads(self, quads):
        """Add quads to the MemoryStore.

        Args:
            quads: Rdflib.quads that should be added to the MemoryStore.
        """
        self.store.addN(quads)
        self.store.commit()

    def query(self, querystring):
        """Execute a SPARQL select query.

        Args:
            querystring: A string containing a SPARQL ask or select query.
        Returns:
            The SPARQL result set
        """
        return self.store.query(querystring)

    def update(self, querystring, versioning=True):
        """Execute a SPARQL update query and update the store.

        This method executes a SPARQL update query and updates and commits all affected files.

        Args:
            querystring: A string containing a SPARQL upate query.
        """
        # methods of rdflib ConjunciveGraph
        if versioning:
            actions = evalUpdate(self.store, querystring)
            self.store.update(querystring)
            return actions
        else:
            self.store.update(querystring)
            return

        return

    def removequads(self, quads):
        """Remove quads from the MemoryStore.

        Args:
            quads: Rdflib.quads that should be removed to the MemoryStore.
        """
        self.store.remove((quads))
        self.store.commit()
        return

    def exit(self):
        """Execute actions on API shutdown."""
        return


class MemoryStore(Store):
    def __init__(self, additional_bindings=list()):
        store = ConjunctiveGraph(identifier='default')
        for prefix, namespace in [('quit', QUIT), ('foaf', FOAF)]:
            store.bind(prefix, namespace)
        for prefix, namespace in additional_bindings:
            store.bind(prefix, namespace)
        super().__init__(store=store)


class VirtualGraph(Queryable):
    def __init__(self, store):
        if not isinstance(store, InMemoryGraphAggregate):
            raise Exception()
        self.store = store

    def query(self, querystring):
        return self.store.query(querystring)

    def update(self, querystring, versioning=True):
        return self.store.update(querystring)


class Quit(object):
    def __init__(self, config, repository, store):
        self.config = config
        self.repository = repository
        self.store = store

    def sync(self, rebuild=False):
        """
        Synchronizes store with repository data.
        """
        if rebuild:
            for c in self.store.contexts():
                self.store.remove((None, None, None), c)

        def exists(id):
            uri = QUIT['commit-' + id]
            for _ in self.store.store.quads((uri, None, None, QUIT.default)):
                return True
            return False

        def traverse(commit, seen):
            commits = []
            merges = []

            while True:
                id = commit.id
                if id in seen:
                    break
                seen.add(id)
                if exists(id):
                    break
                commits.append(commit)
                parents = commit.parents
                if not parents:
                    break
                commit = parents[0]
                if len(parents) > 1:
                    merges.append((len(commits), parents[1:]))
            for idx, parents in reversed(merges):
                for parent in parents:
                    commits[idx:idx] = traverse(parent, seen)
            return commits

        seen = set()

        for name in self.repository.tags_or_branches:
            initial_commit = self.repository.revision(name)
            commits = traverse(initial_commit, seen)

            prov = self.changesets(commits)
            self.store.addquads((s, p, o, c) for s, p, o, c in prov.quads())

            # for commit in commits:
            #     (_, g) = commit.__prov__()
            #     self.store += g

    @lru_cache()
    def instance(self, id=None, force=False):
        default_graphs = list()

        if id:
            commit = self.repository.revision(id)

            _m = self.config.getgraphurifilemap()

            for entity in commit.node().entries(recursive=True):
                # todo check if file was changed
                if entity.is_file:
                    if entity.name not in _m.values():
                        continue

                    tmp = ConjunctiveGraph()
                    tmp.parse(data=entity.content, format='nquads')

                    for context in (c.identifier for c in tmp.contexts()):

                        # Todo: why?
                        if context not in _m:
                            continue

                        identifier = context + '-' + entity.blob.hex
                        rewritten_identifier = context

                        if force or not self.config.checkStoremode(STORE_DATA):
                            g = Graph(identifier=rewritten_identifier)
                            g += tmp.triples((None, None, None))
                        else:
                            g = ReadOnlyRewriteGraph(self.store.store.store,
                                                     identifier, rewritten_identifier)
                        default_graphs.append(g)

        instance = InMemoryGraphAggregate(graphs=default_graphs, identifier='default')

        return VirtualGraph(instance)

    def changesets(self, commits=None):
        g = ConjunctiveGraph(identifier=QUIT.default)

        if not commits or (
            not self.config.checkStoremode(STORE_DATA) and
            not self.config.checkStoremode(STORE_PROVENANCE)
        ):
            return g

        last = None

        if self.config.checkStoremode(STORE_PROVENANCE):
            role_author_uri = QUIT['author']
            role_committer_uri = QUIT['committer']

            g.add((role_author_uri, is_a, PROV['Role']))
            g.add((role_committer_uri, is_a, PROV['Role']))

        while commits:
            commit = commits.pop()
            rev = commit.id

            # Create the commit
            commit_graph = self.instance(commit.id, True)
            commit_uri = QUIT['commit-' + commit.id]

            if self.config.checkStoremode(STORE_PROVENANCE):
                g.add((commit_uri, is_a, PROV['Activity']))

                if 'Source' in commit.properties.keys():
                    g.add((commit_uri, is_a, QUIT['Import']))
                    g.add((commit_uri, QUIT['dataSource'], Literal(
                        commit.properties['Source'].strip())))
                if 'Query' in commit.properties.keys():
                    g.add((commit_uri, is_a, QUIT['Transformation']))
                    g.add((commit_uri, QUIT['query'], Literal(commit.properties['Query'].strip())))

                g.add((commit_uri, QUIT['hex'], Literal(commit.id)))
                g.add((commit_uri, PROV['startedAtTime'], Literal(
                    commit.author_date, datatype=XSD.dateTime)))
                g.add((commit_uri, PROV['endedAtTime'], Literal(
                    commit.committer_date, datatype=XSD.dateTime)))
                g.add((commit_uri, RDFS['comment'], Literal(commit.message.strip())))

                # Author
                hash = pygit2.hash(commit.author.email).hex
                author_uri = QUIT['user-' + hash]
                g.add((commit_uri, PROV['wasAssociatedWith'], author_uri))

                g.add((author_uri, is_a, PROV['Agent']))
                g.add((author_uri, RDFS.label, Literal(commit.author.name)))
                g.add((author_uri, FOAF.mbox, Literal(commit.author.email)))

                q_author_uri = BNode()
                g.add((commit_uri, PROV['qualifiedAssociation'], q_author_uri))
                g.add((q_author_uri, is_a, PROV['Association']))
                g.add((q_author_uri, PROV['agent'], author_uri))
                g.add((q_author_uri, PROV['role'], role_author_uri))

                if commit.author.name != commit.committer.name:
                    # Committer
                    hash = pygit2.hash(commit.committer.email).hex
                    committer_uri = QUIT['user-' + hash]
                    g.add((commit_uri, PROV['wasAssociatedWith'], committer_uri))

                    g.add((committer_uri, is_a, PROV['Agent']))
                    g.add((committer_uri, RDFS.label, Literal(commit.committer.name)))
                    g.add((committer_uri, FOAF.mbox, Literal(commit.committer.email)))

                    q_committer_uri = BNode()
                    g.add((commit_uri, PROV['qualifiedAssociation'], q_committer_uri))
                    g.add((q_committer_uri, is_a, PROV['Association']))
                    g.add((q_committer_uri, PROV['agent'], author_uri))
                    g.add((q_committer_uri, PROV['role'], role_committer_uri))
                else:
                    g.add((q_author_uri, PROV['role'], role_committer_uri))

                # Parents
                parent = None
                parent_graph = None

                if commit.parents:
                    parent = commit.parents[0]
                    parent_graph = self.instance(parent.id, True)

                    for parent in commit.parents:
                        parent_uri = QUIT['commit-' + parent.id]
                        g.add((commit_uri, QUIT["preceedingCommit"], parent_uri))

                # Diff
                diff = graphdiff(parent_graph.store if parent_graph else None,
                                 commit_graph.store if commit_graph else None)
                for ((resource_uri, _), changesets) in diff.items():
                    for (op, update_graph) in changesets:
                        update_uri = QUIT['update-' + commit.id]
                        op_uri = QUIT[op + '-' + commit.id]
                        g.add((commit_uri, QUIT['updates'], update_uri))
                        g.add((update_uri, QUIT['graph'], resource_uri))
                        g.add((update_uri, QUIT[op], op_uri))
                        g.addN((s, p, o, op_uri) for s, p, o in update_graph)

            # Entities
            _m = self.config.getgraphurifilemap()

            for entity in commit.node().entries(recursive=True):
                # todo check if file was changed
                if entity.is_file:

                    if entity.name not in _m.values():
                        continue

                    tmp = ConjunctiveGraph()
                    tmp.parse(data=entity.content, format='nquads')

                    for context in [c.identifier for c in tmp.contexts()]:

                        # Todo: why?
                        if context not in _m:
                            continue

                        public_uri = context
                        private_uri = context + '-' + entity.blob.hex

                        if self.config.checkStoremode(STORE_PROVENANCE | STORE_DATA):
                            g.add((private_uri, PROV['specializationOf'], public_uri))
                            g.add((private_uri, PROV['wasGeneratedBy'], commit_uri))
                        if self.config.checkStoremode(STORE_DATA):
                            g.addN((s, p, o, private_uri)
                                   for s, p, o in tmp.triples((None, None, None), context))

        return g

    def commit(self, graph, message, index, ref, **kwargs):
        if not graph.store.is_dirty:
            return

        seen = set()

        index = self.repository.index(index)

        files = {}

        for context in graph.store.graphs():
            file = self.config.getfileforgraphuri(
                context.identifier) or self.config.getGlobalFile() or 'unassigned.nq'

            graphs = files.get(file, [])
            graphs.append(context)
            files[file] = graphs

        for file, graphs in files.items():
            g = ReadOnlyGraphAggregate(graphs)

            if len(g) == 0:
                index.remove(file)
            else:
                content = g.serialize(format='nquad-ordered').decode('UTF-8')
                index.add(file, content)

        out = list()
        for k, v in kwargs.items():
            if '\n' in v:
                out.append('%s: "%s"' % (k, v))
            else:
                out.pre('%s: %s' % (k, v))
        out.append('')
        if message:
            out.append(message)
        # message = "\n".join(out)

        author = self.repository._repository.default_signature
        id = index.commit(message, author.name, author.email, ref=ref)

        if id:
            self.repository._repository.set_head(id)
            if not self.repository.is_bare:
                self.repository._repository.checkout(ref, strategy=pygit2.GIT_CHECKOUT_FORCE)
            self.sync()


class GitRepo:
    """A class that manages a git repository.

    This class enables versiong via git for a repository.
    You can stage and commit files and checkout different commits of the repository.
    """

    path = ''
    pathspec = []
    repo = None
    callback = None
    author_name = 'QuitStore'
    author_email = 'quit@quit.aksw.org'
    gcProcess = None

    def __init__(self, path, origin=None, gc=False):
        """Initialize a new repository from an existing directory.

        Args:
            path: A string containing the path to the repository.
            origin: The remote URL where to clone and fetch from and push to
        """
        logger = logging.getLogger('quit.core.GitRepo')
        logger.debug('GitRepo, init, Create an instance of GitStore')
        self.path = path
        self.gc = gc

        if not exists(path):
            try:
                makedirs(path)
            except OSError as e:
                raise Exception('Can\'t create path in filesystem:', path, e)

        try:
            self.repo = Repository(path)
        except KeyError:
            pass
        except AttributeError:
            pass

        if origin:
            self.callback = QuitRemoteCallbacks()

        if self.repo:
            if self.repo.is_bare:
                raise QuitGitRepoError('Bare repositories not supported, yet')

            if origin:
                # set remote
                self.addRemote('origin', origin)
        else:
            if origin:
                # clone
                self.repo = self.cloneRepository(origin, path, self.callback)
            else:
                self.repo = init_repository(path=path, bare=False)

    def cloneRepository(self, origin, path, callback):
        try:
            repo = clone_repository(
                url=origin,
                path=path,
                bare=False,
                callbacks=callback
            )
            return repo
        except Exception as e:
            raise QuitGitRepoError(
                "Could not clone from: {} origin. {}".format(
                    origin,
                    e
                )
            )

    def addall(self):
        """Add all (newly created|changed) files to index."""
        self.repo.index.read()
        self.repo.index.add_all(self.pathspec)
        self.repo.index.write()

    def addfile(self, filename):
        """Add a file to the index.

        Args:
            filename: A string containing the path to the file.
        """
        index = self.repo.index
        index.read()

        try:
            index.add(filename)
            index.write()
        except Exception as e:
            logger.info("GitRepo, addfile, Could not add file  {}.".format(filename))
            logger.debug(e)

    def addRemote(self, name, url):
        """Add a remote.

        Args:
            name: A string containing the name of the remote.
            url: A string containing the url to the remote.
        """
        try:
            self.repo.remotes.create(name, url)
            logger.info("Successfully added remote: {} - {}".format(name, url))
        except Exception as e:
            logger.info("Could not add remote: {} - {}".format(name, url))
            logger.debug(e)

        try:
            self.repo.remotes.set_push_url(name, url)
            self.repo.remotes.set_url(name, url)
        except Exception as e:
            logger.info("Could not set push/fetch urls: {} - {}".format(name, url))
            logger.debug(e)

    def checkout(self, commitid):
        """Checkout a commit by a commit id.

        Args:
            commitid: A string cotaining a commitid.
        """
        try:
            commit = self.repo.revparse_single(commitid)
            self.repo.set_head(commit.oid)
            self.repo.reset(commit.oid, GIT_RESET_HARD)
            logger.info("Checked out commit: {}".format(commitid))
        except Exception as e:
            logger.info("Could not check out commit: {}".format(commitid))
            logger.debug(e)

    def commit(self, message=None):
        """Commit staged files.

        Args:
            message: A string for the commit message.
        Raises:
            Exception: If no files in staging area.
        """
        if self.isstagingareaclean():
            # nothing to commit
            return

        index = self.repo.index
        index.read()
        tree = index.write_tree()

        try:
            author = Signature(self.author_name, self.author_email)
            comitter = Signature(self.author_name, self.author_email)

            if len(self.repo.listall_reference_objects()) == 0:
                # Initial Commit
                if message is None:
                    message = 'Initial Commit from QuitStore'
                self.repo.create_commit('HEAD',
                                        author, comitter, message,
                                        tree,
                                        [])
            else:
                if message is None:
                    message = 'New Commit from QuitStore'
                self.repo.create_commit('HEAD',
                                        author, comitter, message,
                                        tree,
                                        [self.repo.head.get_object().hex]
                                        )
            logger.info('Updates commited')
        except Exception as e:
            logger.info('Nothing to commit')
            logger.debug(e)

        if self.gc:
            self.garbagecollection()

    def commitexists(self, commitid):
        """Check if a commit id is part of the repository history.

        Args:
            commitid: String of a Git commit id.
        Returns:
            True, if commitid is part of commit log
            False, else.
        """
        if commitid in self.getids():
            return True
        else:
            return False

    def garbagecollection(self):
        """Start garbage collection.

        Args:
            commitid: A string cotaining a commitid.
        """
        try:
            # Check if the garbage collection process is still running
            if self.gcProcess is None or self.gcProcess.poll() is not None:
                # Start garbage collection with "--auto" option,
                # which imidietly terminates, if it is not necessary
                self.gcProcess = Popen(["git", "gc", "--auto", "--quiet"], cwd=self.path)
                logger.debug('Spawn garbage collection')
        except Exception as e:
            logger.debug('Git garbage collection failed to spawn')
            logger.debug(e)

    def getpath(self):
        """Return the path of the git repository.

        Returns:
            A string containing the path to the directory of git repo
        """
        return self.path

    def getcommits(self):
        """Return meta data about exitsting commits.

        Returns:
            A list containing dictionaries with commit meta data
        """
        commits = []
        if len(self.repo.listall_reference_objects()) > 0:
            for commit in self.repo.walk(self.repo.head.target, GIT_SORT_REVERSE):
                commits.append({
                    'id': str(commit.oid),
                    'message': str(commit.message),
                    'commit_date': datetime.fromtimestamp(
                        commit.commit_time).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'author_name': commit.author.name,
                    'author_email': commit.author.email,
                    'parents': [c.hex for c in commit.parents],
                })
        return commits

    def getids(self):
        """Return meta data about exitsting commits.

        Returns:
            A list containing dictionaries with commit meta data
        """
        ids = []
        if len(self.repo.listall_reference_objects()) > 0:
            for commit in self.repo.walk(self.repo.head.target, GIT_SORT_REVERSE):
                ids.append(str(commit.oid))
        return ids

    def isgarbagecollectionon(self):
        """Return if gc is activated or not.

        Returns:
            True, if activated
            False, if not
        """
        return self.gc

    def isstagingareaclean(self):
        """Check if staging area is clean.

        Returns:
            True, if staginarea is clean
            False, else.
        """
        status = self.repo.status()

        for filepath, flags in status.items():
            if flags != GIT_STATUS_CURRENT:
                return False

        return True

    def pull(self, remote='origin', branch='master'):
        """Pull if possible.

        Return:
            True: If successful.
            False: If merge not possible or no updates from remote.
        """
        try:
            self.repo.remotes[remote].fetch()
        except Exception as e:
            logger.info("Can not pull:  Remote {} not found.".format(remote))
            logger.debug(e)

        ref = 'refs/remotes/' + remote + '/' + branch
        remoteid = self.repo.lookup_reference(ref).target
        analysis, _ = self.repo.merge_analysis(remoteid)

        if analysis & GIT_MERGE_ANALYSIS_UP_TO_DATE:
            # Already up-to-date
            pass
        elif analysis & GIT_MERGE_ANALYSIS_FASTFORWARD:
            # fastforward
            self.repo.checkout_tree(self.repo.get(remoteid))
            master_ref = self.repo.lookup_reference('refs/heads/master')
            master_ref.set_target(remoteid)
            self.repo.head.set_target(remoteid)
        elif analysis & GIT_MERGE_ANALYSIS_NORMAL:
            self.repo.merge(remoteid)
            tree = self.repo.index.write_tree()
            msg = 'Merge from ' + remote + ' ' + branch
            author = Signature(self.author_name, self.author_email)
            comitter = Signature(self.author_name, self.author_email)
            self.repo.create_commit('HEAD',
                                    author,
                                    comitter,
                                    msg,
                                    tree,
                                    [self.repo.head.target, remoteid])
            self.repo.state_cleanup()
        else:
            logger.debug('Can not pull. Unknown merge analysis result')

    def push(self, remote='origin', branch='master'):
        """Push if possible.

        Return:
            True: If successful.
            False: If diverged or nothing to push.
        """
        ref = ['refs/heads/' + branch]

        try:
            remo = self.repo.remotes[remote]
        except Exception as e:
            logger.info("Can not push. Remote: {} does not exist.".format(remote))
            logger.debug(e)
            return

        try:
            remo.push(ref, callbacks=self.callback)
        except Exception as e:
            logger.info("Can not push to {} with ref {}".format(remote, str(ref)))
            logger.debug(e)

    def getRemotes(self):
        remotes = {}

        try:
            for remote in self.repo.remotes:
                remotes[remote.name] = [remote.url, remote.push_url]
        except Exception as e:
            logger.info('No remotes found.')
            logger.debug(e)
            return {}

        return remotes


class QuitRemoteCallbacks (RemoteCallbacks):
    """Set a pygit callback for user authentication when acting with remotes."""

    def credentials(self, url, username_from_url, allowed_types):
        """
        The callback to return a suitable authentication method.

        it supports GIT_CREDTYPE_SSH_KEY and GIT_CREDTYPE_USERPASS_PLAINTEXT
        GIT_CREDTYPE_SSH_KEY with an ssh agent configured in the env variable SSH_AUTH_SOCK
          or with id_rsa and id_rsa.pub in ~/.ssh (password must be the empty string)
        GIT_CREDTYPE_USERPASS_PLAINTEXT from the env variables GIT_USERNAME and GIT_PASSWORD
        """
        if credentials.GIT_CREDTYPE_SSH_KEY & allowed_types:
            if "SSH_AUTH_SOCK" in environ:
                # Use ssh agent for authentication
                return KeypairFromAgent(username_from_url)
            else:
                ssh = join(expanduser('~'), '.ssh')
                if "QUIT_SSH_KEY_HOME" in environ:
                    ssh = environ["QUIT_SSH_KEY_HOME"]
                # public key is still needed because:
                # _pygit2.GitError: Failed to authenticate SSH session:
                # Unable to extract public key from private key file:
                # Method unimplemented in libgcrypt backend
                pubkey = join(ssh, 'id_rsa.pub')
                privkey = join(ssh, 'id_rsa')
                # check if ssh key is available in the directory
                if isfile(pubkey) and isfile(privkey):
                    return Keypair(username_from_url, pubkey, privkey, "")
                else:
                    raise Exception(
                        "No SSH keys could be found, please specify SSH_AUTH_SOCK or add keys to " +
                        "your ~/.ssh/"
                    )
        elif credentials.GIT_CREDTYPE_USERPASS_PLAINTEXT & allowed_types:
            if "GIT_USERNAME" in environ and "GIT_PASSWORD" in environ:
                return UserPass(environ["GIT_USERNAME"], environ["GIT_PASSWORD"])
            else:
                raise Exception(
                    "Remote requested plaintext username and password authentication but " +
                    "GIT_USERNAME or GIT_PASSWORD are not set."
                )
        else:
            raise Exception("Only unsupported credential types allowed by remote end")
