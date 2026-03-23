from neo4j_graph.models import DataElements
from neo4j_graph.services.graphsubtree_service import GraphSubtreeService


class DataElementService:

    @staticmethod
    def get_subtree_by_id(data_element_id, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('DataElements', 'uid', data_element_id, depth, direction)

    @staticmethod
    def get_subtree_by_name(data_element_name, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('DataElements', 'name', data_element_name, depth, direction)

    @staticmethod
    def get_all_data_elements():
        return [{"uid": de.uid, "name": de.name} for de in DataElements.nodes.all()]
