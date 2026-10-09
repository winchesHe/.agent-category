# Bundle Repo Resolution

MoeGo Web bundle 分类与候选仓库映射速查。

| Bundle prefix | Repository | Notes |
|---------------|-----------|-------|
| `lib-moego-ui.*` | `MoeGolibrary/moego-ui` | UI component library |
| `index~*` | `MoeGolibrary/Boarding_Desktop` | Main business application |
| `boarding/*` | `MoeGolibrary/Boarding_Desktop` | Boarding business bundle |
| `online-booking/*` | `MoeGolibrary/online-booking-client-web` | Online booking bundle |
| `app/*` / `src/*` | `MoeGolibrary/website` | Website application bundles |
| `lib-base.*` | internal shared runtime | 仅分类为 UI library bundle；当前不会生成 repo candidate |

这些映射只产生 repo candidate。bundle 名可能被构建配置复用，且缺少 sourcemap 时文件名无法定位源码；最终修复仓库和代码位置仍需结合 route context、符号化 stack 与代码验证。
