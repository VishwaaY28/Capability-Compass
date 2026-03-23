import type { Direction } from './types'

interface ControlPanelProps {
  depth: number
  setDepth: (depth: number) => void
  direction: Direction
  setDirection: (direction: Direction) => void
}

export default function ControlPanel({ depth, setDepth, direction, setDirection }: ControlPanelProps) {
  return (
    <div className="control-panel">
      <div className="control-group">
        <label>Depth:</label>
        <select value={depth} onChange={(e) => setDepth(Number(e.target.value))}>
          {[1,2,3,4,5,6,7,8,9,10].map(n => <option key={n} value={n}>{n}</option>)}
          <option value="0">All</option>
        </select>
      </div>
      <div className="control-group">
        <label>Direction:</label>
        <select value={direction} onChange={(e) => setDirection(e.target.value as Direction)}>
          <option value="outgoing">Outgoing</option>
          <option value="incoming">Incoming</option>
          <option value="both">Both</option>
        </select>
      </div>
    </div>
  )
}
