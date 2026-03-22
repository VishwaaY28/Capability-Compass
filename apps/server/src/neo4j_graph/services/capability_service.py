from neo4j_graph.models import Capability
from neo4j_graph.services.graphsubtree_service import GraphSubtreeService


class CapabilityService:

    @staticmethod
    def get_subtree_by_id(capability_id, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('Capability', 'uid', capability_id, depth, direction)

    @staticmethod
    def get_subtree_by_name(capability_name, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('Capability', 'name', capability_name, depth, direction)

    @staticmethod
    def get_all_capabilities():
        return [{"uid": c.uid, "name": c.name} for c in Capability.nodes.all()]

    @staticmethod
    def delete_by_id(capability_id):
        try:
            Capability.nodes.get(uid=capability_id).delete()
            return True
        except Capability.DoesNotExist:
            return False

    @staticmethod
    def delete_by_name(capability_name):
        try:
            Capability.nodes.get(name=capability_name).delete()
            return True
        except Capability.DoesNotExist:
            return False
