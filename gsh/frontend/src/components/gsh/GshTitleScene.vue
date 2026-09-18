<script lang="ts">
import { defineComponent } from 'vue';
import { buildGshTitleScene } from './gsh-title-scene';
import { useAmbientMotion } from '@/composables/useAmbientMotion';

export default defineComponent({
  name: 'GshTitleScene',
  setup() {
    const { ambientMotion } = useAmbientMotion(true);
    return () => buildGshTitleScene(ambientMotion.value);
  },
});
</script>
