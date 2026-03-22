from neo4j_graph.models import Process
from neo4j_graph.services.graphsubtree_service import GraphSubtreeService


class ProcessService:

    @staticmethod
    def get_subtree_by_id(process_id, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('Process', 'uid', process_id, depth, direction)

    @staticmethod
    def get_subtree_by_name(process_name, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('Process', 'name', process_name, depth, direction)

    @staticmethod
    def get_all_processes():
        return [{"uid": p.uid, "name": p.name} for p in Process.nodes.all()]
