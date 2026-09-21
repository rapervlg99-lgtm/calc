import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { fetchProfileCatalog } from '../utils/extApi'
import { buildProfileOptions, type ProfileOption } from '../utils/profileSuggest'

/**
 * Справочник марок проката для подсказок при ручном вводе номера профиля.
 * Грузится лениво при первом фокусе в поле марки, один раз на сессию.
 */
export const useProfileCatalogStore = defineStore('profileCatalog', () => {
  const options = ref<ProfileOption[]>([])
  const loading = ref(false)
  const loaded = ref(false)

  const ready = computed(() => loaded.value && options.value.length > 0)

  async function load(): Promise<void> {
    if (loaded.value || loading.value) return
    loading.value = true
    try {
      options.value = buildProfileOptions(await fetchProfileCatalog())
      loaded.value = options.value.length > 0
    } finally {
      loading.value = false
    }
  }

  return { options, loading, loaded, ready, load }
})
