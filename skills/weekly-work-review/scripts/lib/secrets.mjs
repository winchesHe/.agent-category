// PRIVACY-002：整包凭证形状扫描。
// 命中只输出文件、行号和规则，绝不回显凭证原文。
// 会议原文可保留姓名、客户名、说话人；凭证形状不豁免。

const RULES = [
  { id: 'SECRET-001', label: 'Authorization header', pattern: /\bAuthorization\s*[:=]\s*\S/i },
  { id: 'SECRET-002', label: 'Bearer token', pattern: /\bBearer\s+[A-Za-z0-9._~+/-]{16,}/ },
  { id: 'SECRET-003', label: 'access_token', pattern: /\baccess_token\s*[:=]\s*['"]?[A-Za-z0-9._~+/-]{12,}/i },
  { id: 'SECRET-004', label: 'refresh_token', pattern: /\brefresh_token\s*[:=]\s*['"]?[A-Za-z0-9._~+/-]{12,}/i },
  { id: 'SECRET-005', label: 'client_secret', pattern: /\bclient_secret\s*[:=]\s*['"]?\S{8,}/i },
  { id: 'SECRET-006', label: 'api_key', pattern: /\b(api[_-]?key|apikey)\s*[:=]\s*['"]?[A-Za-z0-9._~+/-]{12,}/i },
  { id: 'SECRET-007', label: 'password', pattern: /\bpassword\s*[:=]\s*['"]?\S{6,}/i },
  { id: 'SECRET-008', label: 'private key block', pattern: /-----BEGIN [A-Z ]*PRIVATE KEY-----/ },
  { id: 'SECRET-009', label: 'sk- style key', pattern: /\bsk-[A-Za-z0-9_-]{20,}/ },
  { id: 'SECRET-010', label: '1Password credential ref', pattern: /\bop:\/\/\S+\/credential/ },
  { id: 'SECRET-011', label: 'Anthropic auth token', pattern: /\bANTHROPIC_AUTH_TOKEN\s*[:=]\s*\S/ },
  { id: 'SECRET-012', label: 'Slack token', pattern: /\bxox[abposr]-[A-Za-z0-9-]{10,}/ },
  { id: 'SECRET-013', label: 'GitHub token', pattern: /\bgh[pousr]_[A-Za-z0-9]{20,}/ },
  { id: 'SECRET-014', label: 'AWS access key id', pattern: /\bAKIA[0-9A-Z]{16}\b/ },
  { id: 'SECRET-015', label: 'service account json', pattern: /"type"\s*:\s*"service_account"/ },
  { id: 'SECRET-016', label: 'credentials file reference', pattern: /\bcredentials\.json\b/ },
];

// 占位符与文档示例不算泄漏
const PLACEHOLDER = /(<[^>\n]{2,40}>|\{\{[^}\n]+\}\}|\$\{[A-Z_]+\}|xxx+|\*{4,}|REDACTED|PLACEHOLDER|example|示例|填入|your-|<your)/i;

export function scanTextForSecrets(text, relPath) {
  const findings = [];
  const lines = String(text || '').split(/\r?\n/);
  lines.forEach((line, index) => {
    // .env.example 风格的空赋值不是泄漏
    if (/^[A-Z_]+=\s*$/.test(line.trim())) return;
    for (const rule of RULES) {
      if (!rule.pattern.test(line)) continue;
      if (PLACEHOLDER.test(line)) continue;
      findings.push({
        rule_id: rule.id,
        label: rule.label,
        file: relPath,
        line: index + 1,
      });
    }
  });
  return findings;
}

export const SECRET_RULES = RULES;
