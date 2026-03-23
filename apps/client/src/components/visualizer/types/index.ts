export interface NodeProperties {
  uid: number
  name: string
  description?: string
  level?: number
  category?: string
  vertical?: string
  subvertical?: string
  data_entity_description?: string
  data_element_description?: string
}

export interface ApiNode {
  internal_id: number
  labels: string[]
  properties: NodeProperties
  relationships?: Record<string, ApiNode[]>
}

export interface ApiResponse {
  root: ApiNode
  node_depths: Record<string, number>
  max_depth: number
}

export interface EntityListItem {
  uid: number
  name: string
}

export type EntityType = 'Capability' | 'Process' | 'Subprocess' | 'DataEntity' | 'DataElement' | 'OrgUnit' | 'ApplicationCatalog'

export type Direction = 'outgoing' | 'incoming' | 'both'
