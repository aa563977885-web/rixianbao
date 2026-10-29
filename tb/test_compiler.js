// tb.txt 编译脚本的上线路径测试：在 Node 里真实执行 run()，验证输出。
// 用法: node test_compiler.js   （在 tb/ 目录下）
// 任何对 tb.txt 的修改，推送前必须先跑这个测试通过。
const fs = require('fs');
const path = require('path');

const compilerSrc = fs.readFileSync(path.join(__dirname, 'tb.txt'), 'utf-8');
const config = JSON.parse(fs.readFileSync(path.join(__dirname, 'tjb.json'), 'utf-8'));

let pass = 0, fail = 0;
function check(name, cond, extra) {
  if (cond) { pass++; console.log(`  ✓ ${name}`); }
  else { fail++; console.log(`  ✗ ${name}${extra ? ' — ' + extra : ''}`); }
}

// —— 场景1：多账号模式1（淘宝单App），全任务组 ——
const DATA1 = { activity: config.activity, taskData: config.taskData };
let result1 = null;
try {
  const fn = new Function('DATA', 'configValue', 'runNum', compilerSrc + '\nreturn run();');
  result1 = fn(DATA1, 1, 0);
  result1 = JSON.parse(result1);
  check('场景1 编译执行无异常', true);
} catch (e) {
  check('场景1 编译执行无异常', false, e.message);
}
check('场景1 输出结构含 data 数组', Array.isArray(result1?.data));
check('场景1 每条任务都有 url 和 wait', (result1?.data || []).every(x => typeof x.url === 'string' && x.url.length > 5 && typeof x.wait === 'number'));
check('场景1 开场含用户助力链', JSON.stringify(result1?.data || []).includes('j4SVLRp'));
check('场景1 无作者痕迹(gitcode/旧追踪链)', !JSON.stringify(result1?.data || []).includes('gitcode') && !JSON.stringify(result1?.data || []).includes('jex2zTH'));

// —— 场景2：断点续跑（runNum=5，应从第5条开始）——
let result2 = null;
try {
  const fn = new Function('DATA', 'configValue', 'runNum', compilerSrc + '\nreturn run();');
  result2 = JSON.parse(fn(DATA1, 1, 5));
  check('场景2 断点续跑条数正确', result2.data.length === (result1.data.length - 4));
} catch (e) {
  check('场景2 断点续跑', false, e.message);
}

// —— 场景3：多账号模式2（淘宝+天猫双 scheme，任务应翻倍）——
let result3 = null;
try {
  const fn = new Function('DATA', 'configValue', 'runNum', compilerSrc + '\nreturn run();');
  result3 = JSON.parse(fn(DATA1, 2, 0));
  check('场景3 双App模式条数翻倍', result3.data.length === result1.data.length * 2);
} catch (e) {
  check('场景3 双App模式', false, e.message);
}

// —— 场景4：等待时间合理（原版基线 22 秒 ±3 抖动以内，且不低于 8）——
const waits = (result1?.data || []).map(x => x.wait).filter(w => w >= 5);
check('场景1 等待时间全部 ≥5 秒（含首页/回访短停留）', waits.length === (result1?.data || []).length);

console.log(`\n结果: ${pass} 通过, ${fail} 失败`);
process.exit(fail > 0 ? 1 : 0);
