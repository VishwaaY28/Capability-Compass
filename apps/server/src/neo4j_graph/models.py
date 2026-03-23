from neomodel import StructuredNode, RelationshipTo, RelationshipFrom, StringProperty, IntegerProperty


class Vertical(StructuredNode):
    uid = IntegerProperty(unique_index=True)
    name = StringProperty(unique_index=True)
    has_subvertical = RelationshipTo('SubVertical', 'HAS_SUBVERTICAL')


class SubVertical(StructuredNode):
    uid = IntegerProperty(unique_index=True)
    name = StringProperty(unique_index=True)
    belongs_to_vertical = RelationshipFrom('Vertical', 'HAS_SUBVERTICAL')
    has_capability = RelationshipTo('Capability', 'HAS_CAPABILITY')


class Capability(StructuredNode):
    uid = IntegerProperty(unique_index=True)
    name = StringProperty(unique_index=True)
    description = StringProperty()
    vertical = StringProperty()
    subvertical = StringProperty()
    realized_by = RelationshipTo('Process', 'REALIZED_BY')
    accountable_for = RelationshipTo('OrganizationUnit', 'ACCOUNTABLE')
    belongs_to_subvertical = RelationshipFrom('SubVertical', 'HAS_CAPABILITY')
    has_chunk = RelationshipTo('Chunk', 'HAS_CHUNK')


class Process(StructuredNode):
    uid = IntegerProperty(unique_index=True)
    name = StringProperty(unique_index=True)
    level = IntegerProperty()
    description = StringProperty()
    category = StringProperty()
    decomposes = RelationshipTo('Subprocess', 'DECOMPOSES')
    realized_by = RelationshipFrom('Capability', 'REALIZED_BY')


class Subprocess(StructuredNode):
    uid = IntegerProperty(unique_index=True)
    name = StringProperty(unique_index=True)
    description = StringProperty()
    category = StringProperty()
    uses_data = RelationshipTo('DataEntity', 'USES_DATA')
    decomposes = RelationshipFrom('Process', 'DECOMPOSES')
    supports = RelationshipTo('ApplicationCatalog', 'SUPPORTED_BY')


class DataEntity(StructuredNode):
    uid = IntegerProperty(unique_index=True)
    name = StringProperty(unique_index=True)
    data_entity_description = StringProperty()
    has_element = RelationshipTo('DataElements', 'HAS_ELEMENT')
    uses_data = RelationshipFrom('Subprocess', 'USES_DATA')


class DataElements(StructuredNode):
    uid = IntegerProperty(unique_index=True)
    name = StringProperty(unique_index=True)
    data_element_description = StringProperty()
    has_element = RelationshipFrom('DataEntity', 'HAS_ELEMENT')


class OrganizationUnit(StructuredNode):
    uid = IntegerProperty(unique_index=True)
    name = StringProperty(unique_index=True)
    accountable_for = RelationshipFrom('Capability', 'ACCOUNTABLE')


class ApplicationCatalog(StructuredNode):
    uid = IntegerProperty(unique_index=True)
    name = StringProperty(unique_index=True)
    supports = RelationshipFrom('Subprocess', 'SUPPORTED_BY')


class Chunk(StructuredNode):
    """Knowledge chunk node for RAG/semantic search"""
    uid = IntegerProperty(unique_index=True)
    text = StringProperty()
    page = IntegerProperty()
    source = StringProperty()
    embedding = StringProperty()  # Store as JSON string or use ArrayProperty if available
    has_chunk = RelationshipFrom('Capability', 'HAS_CHUNK')
