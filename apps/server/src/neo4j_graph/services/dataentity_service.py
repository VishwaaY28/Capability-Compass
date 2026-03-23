from neo4j_graph.models import DataEntity
from neo4j_graph.services.graphsubtree_service import GraphSubtreeService


class DataEntityService:

    @staticmethod
    def get_subtree_by_id(data_entity_id, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('DataEntity', 'uid', data_entity_id, depth, direction)

    @staticmethod
    def get_subtree_by_name(data_entity_name, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('DataEntity', 'name', data_entity_name, depth, direction)

    @staticmethod
    def get_all_data_entities():
        return [{"uid": de.uid, "name": de.name} for de in DataEntity.nodes.all()]
