## REMOVED Requirements

### Requirement: PII Notice Before Resume Upload

**Reason**: 个人项目取消隐私承诺;草稿现在会保存简历原文以支持全保真续答,原「简历原文不持久化」通知不再成立。

**Migration**: 无。移除 sidebar / uploader / config 页的 PII 通知文案,无数据迁移。

### Requirement: ToS Versioned Acceptance

**Reason**: 个人项目取消服务条款接受闸门,降低启动摩擦。

**Migration**: 无。移除入口 ToS modal 与 `tos_accepted`/`tos_check_done` 状态;老 DB 的 `consent_log` 表遗留无害。

### Requirement: Consent Log Persistence

**Reason**: 随 ToS 闸门一并移除,不再需要审计接受记录。

**Migration**: 无。删除 `consent_log` 表定义与 `record_consent`/`has_accepted_tos`;老 DB 遗留表不清理。
