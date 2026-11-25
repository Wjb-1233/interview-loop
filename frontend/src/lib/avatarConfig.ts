/** Shared asset paths and fallback order for interviews and lessons. No service secrets here. */
export type AvatarProvider = 'simli' | 'human' | 'vrm' | 'photo' | 'live2d'
export const avatarAssets = Object.freeze({
  photo: '/avatars/presenter/teacher.png',
  vrm: '/avatars/vrm/sample.vrm',
  human: '/avatars/human/Business_Male_01.fbx',
  humanFace: '/avatars/human/Business_Male_01_facial.fbx',
})

// Preserve the deployed defaults. Simli requires backend configuration; all failures fall back locally.
const defaults: AvatarProvider[] = ['simli', 'human', 'photo', 'live2d']
const providers: AvatarProvider[] = ['simli', 'human', 'vrm', 'photo', 'live2d']
export function avatarOrder(preferred = import.meta.env.VITE_AVATAR_PROVIDER,
  development = import.meta.env.DEV, search = window.location.search): AvatarProvider[] {
  const override = development ? new URLSearchParams(search).get('avatar') : null
  const value = override || preferred
  const first = providers.find(item => item === value)
  return first ? [first, ...defaults.filter(item => item !== first)] : [...defaults]
}
