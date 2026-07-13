import type { DataSource } from './pmoTypes'

interface DataSourceSelectorProps {
  dataSource: DataSource
  setDataSource: (source: DataSource) => void
  className?: string
}

export default function DataSourceSelector({ dataSource, setDataSource, className = '' }: DataSourceSelectorProps) {
  return (
    <div className={`selector-group header-data-source ${className}`.trim()}>
      <label>Database:</label>
      <select
        value={dataSource}
        onChange={(e) => setDataSource(e.target.value as DataSource)}
      >
        <option value="compass">Compass</option>
        <option value="PMO">PMO</option>
      </select>
    </div>
  )
}
