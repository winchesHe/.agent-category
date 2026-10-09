import assert from 'node:assert/strict';
import { inlineTokens } from '../templates/sites/app/reading/inline-tokens.ts';
const tokens = inlineTokens('接口 pay.prePayStatus=-1，状态 NO_PAYMENT。PR https://github.com/MoeGolibrary/moego-api-v3/pull/993（51e412f6f349e195e0162c509658631d37be9529）。');
assert.deepEqual(tokens.filter(t => t.kind === 'code').map(t => t.value), ['pay.prePayStatus=-1','NO_PAYMENT','51e412f6f349e195e0162c509658631d37be9529']);
assert.equal(tokens.find(t => t.kind === 'link').label, 'moego-api-v3 #993');
assert.equal(tokens.find(t => t.kind === 'link').value, 'https://github.com/MoeGolibrary/moego-api-v3/pull/993');
for (const input of ['正常请求仍在。Web 与 Android。','链接 (https://example.com/a_(b)?q=x). 后续。','<img src=x onerror=alert(1)> javascript:alert(1)']) {
 assert.equal(inlineTokens(input).map(t=>t.value).join(''), input);
}
assert.equal(inlineTokens('(https://example.com/a_(b)).').find(t=>t.kind==='link').value,'https://example.com/a_(b)');
assert.deepEqual(inlineTokens('用 `prepayStatus` 字段'), [{kind:'text',value:'用 '},{kind:'code',value:'prepayStatus'},{kind:'text',value:' 字段'}]);
assert.equal(inlineTokens('javascript:alert(1)').some(t=>t.kind==='link'),false);
assert.equal(inlineTokens('https://')[0].kind,'text');
console.log('链接目标、标点保留、代码识别和非链接文本检查通过');
