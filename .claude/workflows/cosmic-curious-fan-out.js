export const meta = {
  name: 'cosmic-curious-fan-out',
  description: 'Fan out topic research, science vetting, and creative asset generation for the Cosmic Curious channel.',
  phases: [{ title: 'Explore' }, { title: 'Vetting' }, { title: 'Production' }],
}

const TOPICS = [
  'What happens when a supernova explodes right next to Earth',
  'Walking on a planet where it rains molten lead',
  'Floating inside the eye of a storm larger than our entire planet',
  'Why stars twinkling is actually a beautiful atmospheric distortion',
  'How light from an ancient galaxy reveals secrets about the beginning of time'
]

// Phase 1: Parallel Topic Exploration
const research = await pipeline(
  TOPICS,
  t => agent(`Research this topic for a 60-second Short: ${t}`, { label: `explore:${t.substring(0, 20)}`, phase: 'Explore' }),
  results => results
)

// Phase 2: Parallel Vetting (Science & Retention)
const vetting = await parallel(research.map(r => () => 
  agent(`Vet this topic for scientific accuracy and high-retention visual potential: ${r}`, { label: `vet:${r.substring(0, 20)}`, phase: 'Vetting' })
))

// Phase 3: Parallel Production Briefing
const production = await parallel(vetting.map(v => () =>
  agent(`Generate a 20-beat production brief including stock footage search queries and script highlights for: ${v}`, { label: `produce:${v.substring(0, 20)}`, phase: 'Production' })
))

return { production }