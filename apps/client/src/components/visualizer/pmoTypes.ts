export interface PmoApiNode {
  internal_id: number | string
  labels: string[]
  properties: Record<string, unknown>
}

export interface PmoFlatRelationship {
  id: string
  type: string
  start_node_id: string
  end_node_id: string
  properties: Record<string, unknown>
}

export interface PmoFlatGraphResponse {
  root_id: string
  nodes: PmoApiNode[]
  relationships: PmoFlatRelationship[]
  node_depths: Record<string, number>
  max_depth: number
}

export type DataSource = 'compass' | 'PMO'

export type PmoLabel =
  | 'Document'
  | 'RiskRecord'
  | 'CapabilityExecution'
  | 'MilestoneRecord'
  | 'KPI'
  | 'Organisation'
  | 'ArtefactSource'
  | 'Capability'
  | 'OnboardingInstance'
  | 'SystemBinding'
  | 'Project'
  | 'Client'
  | 'Person'
  | 'LessonLearned'

export interface PmoEntityListItem {
  uri: string
  name: string
}

export type Direction = 'outgoing' | 'incoming' | 'both'

export const PMO_LABEL_COLORS: Record<string, string> = {
  Document: '#5C6BC0',
  RiskRecord: '#E53935',
  CapabilityExecution: '#00897B',
  MilestoneRecord: '#8E24AA',
  KPI: '#FB8C00',
  Organisation: '#6D4C41',
  ArtefactSource: '#78909C',
  Capability: '#E63946',
  OnboardingInstance: '#1E88E5',
  SystemBinding: '#43A047',
  Project: '#3949AB',
  Client: '#D81B60',
  Person: '#FDD835',
  LessonLearned: '#00ACC1',
}

export const PMO_LEGEND_ITEMS: { label: string; color: string; className: string }[] = [
  { label: 'Document', className: 'pmo-document', color: '#5C6BC0' },
  { label: 'Risk Record', className: 'pmo-riskrecord', color: '#E53935' },
  { label: 'Capability Execution', className: 'pmo-capabilityexecution', color: '#00897B' },
  { label: 'Milestone', className: 'pmo-milestonerecord', color: '#8E24AA' },
  { label: 'KPI', className: 'pmo-kpi', color: '#FB8C00' },
  { label: 'Organisation', className: 'pmo-organisation', color: '#6D4C41' },
  { label: 'Artefact Source', className: 'pmo-artefactsource', color: '#78909C' },
  { label: 'Capability', className: 'pmo-capability', color: '#E63946' },
  { label: 'Onboarding Instance', className: 'pmo-onboardinginstance', color: '#1E88E5' },
  { label: 'System Binding', className: 'pmo-systembinding', color: '#43A047' },
  { label: 'Project', className: 'pmo-project', color: '#3949AB' },
  { label: 'Client', className: 'pmo-client', color: '#D81B60' },
  { label: 'Person', className: 'pmo-person', color: '#FDD835' },
  { label: 'Lesson Learned', className: 'pmo-lessonlearned', color: '#00ACC1' },
]
