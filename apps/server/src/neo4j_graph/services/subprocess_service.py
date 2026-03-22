from neo4j_graph.models import Subprocess
from neo4j_graph.services.graphsubtree_service import GraphSubtreeService


class SubprocessService:

    @staticmethod
    def get_subtree_by_id(subprocess_id, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('Subprocess', 'uid', subprocess_id, depth, direction)

    @staticmethod
    def get_subtree_by_name(subprocess_name, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('Subprocess', 'name', subprocess_name, depth, direction)

    @staticmethod
    def get_all_subprocesses():
        return [{"uid": sp.uid, "name": sp.name} for sp in Subprocess.nodes.all()]
