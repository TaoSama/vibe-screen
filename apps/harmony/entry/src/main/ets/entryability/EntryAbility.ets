import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { window } from '@kit.ArkUI';
import { sessionRuntime } from '../platform/SessionRuntime';

const LOG_DOMAIN: number = 0x56494245;

export default class EntryAbility extends UIAbility {
  onCreate(_want: Want, _launchParam: AbilityConstant.LaunchParam): void {
    hilog.info(LOG_DOMAIN, 'VibeScreen', 'EntryAbility created');
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    windowStage.loadContent('pages/Index', (error) => {
      if (error.code) {
        hilog.error(LOG_DOMAIN, 'VibeScreen', 'loadContent failed: %{public}s', JSON.stringify(error));
      }
    });
  }

  onForeground(): void {
    sessionRuntime.onForeground().catch((error: Error) => hilog.error(LOG_DOMAIN, 'VibeScreen',
      'foreground recovery failed: %{public}s', error.message));
  }

  onBackground(): void {
    sessionRuntime.onBackground().catch((error: Error) => hilog.error(LOG_DOMAIN, 'VibeScreen',
      'background suspend failed: %{public}s', error.message));
  }

  onDestroy(): void {
    sessionRuntime.disconnect().catch((error: Error) => hilog.error(LOG_DOMAIN, 'VibeScreen',
      'session shutdown failed: %{public}s', error.message));
  }
}
