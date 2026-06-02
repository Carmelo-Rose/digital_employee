import pandas as pd
from datetime import datetime, timedelta
import os

desktop = r'C:\Users\Administrator.DESKTOP-GRHN4PA\Desktop'
now = datetime.now()

# ── 1. 电商订单表 ──────────────────────────────────────────────
orders = [
    ['DD20260601001', '旗舰店', '纯棉T恤-白色XL',  128.00, '已付款', now-timedelta(hours=2),  '已发货',    '运输中',    '无退款',   None,                   50, 2, ''],
    ['DD20260601002', '旗舰店', '运动短裤-黑色M',   89.00,  '已付款', now-timedelta(hours=60), '未发货',    '',          '无退款',   None,                   30, 1, '催发货，客户等了三天了'],
    ['DD20260601003', '分销店', '帆布包-米白色',    65.00,  '已付款', now-timedelta(hours=50), '未发货',    '',          '无退款',   None,                    2, 1, ''],
    ['DD20260601004', '旗舰店', '针织开衫-灰色L',  210.00,  '已付款', now-timedelta(hours=1),  '已发货',    '物流异常',  '无退款',   None,                   18, 1, ''],
    ['DD20260601005', '旗舰店', '牛仔裤-蓝色28',   199.00,  '已付款', now-timedelta(hours=3),  '已发货',    '运输中',    '退款中',   now-timedelta(days=8),  15, 1, ''],
    ['DD20260601006', '分销店', '帽子-黑色均码',    45.00,  '已付款', now-timedelta(hours=5),  '已发货',    '运输中',    '无退款',   None,                  200, 2, ''],
    ['DD20260601007', '旗舰店', '连衣裙-碎花S',    320.00,  '已付款', now-timedelta(hours=55), '未发货',    '',          '无退款',   None,                    0, 1, '质量问题，要退款'],
    ['DD20260601008', '旗舰店', '运动鞋-白色42',   368.00,  '已付款', now-timedelta(hours=4),  '已发货',    '运输中',    '无退款',   None,                   25, 1, ''],
    ['DD20260601009', '分销店', '防晒衣-粉色L',    158.00,  '已付款', now-timedelta(hours=6),  '已发货',    '超时未更新','无退款',   None,                   40, 2, ''],
    ['DD20260601010', '旗舰店', '短袖polo-白色M',  135.00,  '已付款', now-timedelta(hours=48), '部分发货',  '',          '退款失败', now-timedelta(days=2),   8, 2, '投诉，要找消费者协会'],
    ['DD20260601011', '旗舰店', '休闲裤-卡其色L',  168.00,  '未付款', None,                    '未发货',    '',          '无退款',   None,                  120, 1, ''],
    ['DD20260601012', '分销店', '背心-白色XS',      38.00,  '已付款', now-timedelta(hours=1),  '已发货',    '运输中',    '无退款',   None,                    3, 2, '库存不够，少发了一件'],
    ['DD20260601013', '旗舰店', '卫衣-深蓝色XL',   258.00,  '已付款', now-timedelta(hours=2),  '已发货',    '运输中',    '无退款',   None,                   60, 1, ''],
    ['DD20260601014', '旗舰店', '皮带-棕色',          0.00,  '已付款', now-timedelta(hours=3),  '已发货',    '运输中',    '无退款',   None,                   35, 1, ''],
    ['DD20260601015', '分销店', '袜子礼盒6双',      58.00,  '已付款', now-timedelta(hours=52), '未发货',    '',          '无退款',   None,                  150, 3, ''],
]
df1 = pd.DataFrame(orders, columns=[
    '订单号', '店铺名称', '商品名称', '订单金额', '支付状态', '支付时间',
    '发货状态', '物流状态', '退款状态', '退款申请时间', '库存数量', '购买数量', '客服备注'
])
df1.to_excel(os.path.join(desktop, '电商订单表_示例.xlsx'), index=False)
print('done 1/4 电商订单表')

# ── 2. HR 人事表 ──────────────────────────────────────────────
hr_data = [
    ['EMP001', '张伟', '技术部', '软件工程师', now-timedelta(days=92),  now+timedelta(days=0),   '试用期', '未提交', ''],
    ['EMP002', '李娜', '市场部', '市场专员',   now-timedelta(days=180), now-timedelta(days=5),   '已转正', '已签署', ''],
    ['EMP003', '王芳', '技术部', '产品经理',   now-timedelta(days=75),  now+timedelta(days=15),  '试用期', '未提交', ''],
    ['EMP004', '赵磊', '销售部', '销售代表',   now-timedelta(days=365), now-timedelta(days=3),   '正式',   '已签署', '合同已到期未续签'],
    ['EMP005', '陈静', 'HR部',   'HR专员',     now-timedelta(days=200), now+timedelta(days=60),  '正式',   '已签署', ''],
    ['EMP006', '刘洋', '技术部', '后端工程师', now-timedelta(days=88),  now+timedelta(days=2),   '试用期', '未提交', ''],
    ['EMP007', '孙丽', '财务部', '财务主管',   now-timedelta(days=730), now+timedelta(days=180), '正式',   '已签署', ''],
    ['EMP008', '周强', '销售部', '区域经理',   now-timedelta(days=95),  now-timedelta(days=5),   '试用期', '未提交', '试用期已过未转正处理'],
    ['EMP009', '吴雪', '市场部', '内容运营',   now-timedelta(days=30),  now+timedelta(days=60),  '试用期', '已签署', ''],
    ['EMP010', '郑明', '技术部', '测试工程师', now-timedelta(days=400), now+timedelta(days=20),  '正式',   '已签署', ''],
    ['EMP011', '黄婷', '客服部', '客服专员',   now-timedelta(days=60),  now+timedelta(days=30),  '试用期', '未签署', '入职一个月合同未签'],
    ['EMP012', '徐刚', '运营部', '运营总监',   now-timedelta(days=800), now+timedelta(days=90),  '离职中', '已签署', '工作交接未完成'],
    ['EMP013', '朱华', '技术部', '前端工程师', now-timedelta(days=45),  now+timedelta(days=45),  '试用期', '已签署', ''],
    ['EMP014', '林萍', '财务部', '出纳',       now-timedelta(days=500), now-timedelta(days=10),  '正式',   '已签署', '合同到期未处理'],
    ['EMP015', '何宇', '销售部', '销售专员',   now-timedelta(days=91),  now-timedelta(days=1),   '试用期', '未提交', '试用期考核表未提交'],
]
df2 = pd.DataFrame(hr_data, columns=[
    '员工编号', '姓名', '部门', '岗位',
    '入职日期', '合同到期日', '员工状态', '转正考核材料', '备注'
])
df2.to_excel(os.path.join(desktop, 'HR人事表_示例.xlsx'), index=False)
print('done 2/4 HR人事表')

# ── 3. 财务报销表 ──────────────────────────────────────────────
expense_data = [
    ['EX20260601001', '张伟', '技术部', '差旅费',    3200.00,  now-timedelta(days=15), now-timedelta(days=14), '审批中',   '已提交', '出差上海3天'],
    ['EX20260601002', '李娜', '市场部', '餐饮招待',  8500.00,  now-timedelta(days=3),  now-timedelta(days=3),  '待审批',   '已提交', '客户招待，金额超标'],
    ['EX20260601003', '王芳', '技术部', '办公用品',   320.00,  now-timedelta(days=2),  now-timedelta(days=2),  '已审批',   '已提交', ''],
    ['EX20260601004', '赵磊', '销售部', '差旅费',    1800.00,  now-timedelta(days=20), now-timedelta(days=20), '审批中',   '未提交', '发票未附'],
    ['EX20260601005', '陈静', 'HR部',   '培训费',    5000.00,  now-timedelta(days=5),  now-timedelta(days=5),  '待审批',   '已提交', ''],
    ['EX20260601006', '刘洋', '技术部', '设备采购',     0.00,  now-timedelta(days=1),  now-timedelta(days=1),  '待审批',   '已提交', '金额录入异常'],
    ['EX20260601007', '孙丽', '财务部', '差旅费',    2600.00,  now-timedelta(days=18), now-timedelta(days=17), '审批中',   '已提交', ''],
    ['EX20260601008', '周强', '销售部', '客户礼品', 12000.00,  now-timedelta(days=4),  now-timedelta(days=4),  '待审批',   '已提交', '超出礼品费预算上限'],
    ['EX20260601009', '吴雪', '市场部', '广告投放', 45000.00,  now-timedelta(days=7),  now-timedelta(days=7),  '已审批',   '已提交', ''],
    ['EX20260601010', '郑明', '技术部', '差旅费',     980.00,  now-timedelta(days=25), now-timedelta(days=25), '审批中',   '未提交', '审批超25天未完成，发票缺失'],
    ['EX20260601011', '黄婷', '客服部', '办公用品',   150.00,  now-timedelta(days=1),  now-timedelta(days=1),  '已审批',   '已提交', ''],
    ['EX20260601012', '徐刚', '运营部', '团建费',    6800.00,  now-timedelta(days=8),  now-timedelta(days=8),  '审批驳回', '已提交', '超预算被驳回未重新提交'],
    ['EX20260601013', '朱华', '技术部', '软件订阅',   299.00,  now-timedelta(days=2),  now-timedelta(days=2),  '已审批',   '已提交', ''],
    ['EX20260601014', '林萍', '财务部', '差旅费',    -100.00,  now-timedelta(days=3),  now-timedelta(days=3),  '待审批',   '已提交', '金额为负，数据异常'],
    ['EX20260601015', '何宇', '销售部', '差旅费',    2100.00,  now-timedelta(days=22), now-timedelta(days=21), '审批中',   '未提交', '发票未附，审批已拖延'],
]
df3 = pd.DataFrame(expense_data, columns=[
    '报销单号', '申请人', '部门', '费用类型', '报销金额',
    '申请日期', '提交日期', '审批状态', '发票状态', '备注'
])
df3.to_excel(os.path.join(desktop, '财务报销表_示例.xlsx'), index=False)
print('done 3/4 财务报销表')

# ── 4. 供应商对账表 ──────────────────────────────────────────────
supplier_data = [
    ['INV20260501001', '优质纺织有限公司', '面料采购',  28000.00, 27800.00,  200.00, now-timedelta(days=35), now-timedelta(days=5),  '账期超时', '未付款', '账期30天，已超期5天'],
    ['INV20260501002', '创新包装科技',     '包装材料',   5600.00,  5600.00,    0.00, now-timedelta(days=20), now-timedelta(days=18), '正常',     '已付款', ''],
    ['INV20260501003', '速达物流集团',     '仓储物流',  12300.00, 11900.00,  400.00, now-timedelta(days=15), None,                   '对账差异', '待付款', '对账金额不符，差400元'],
    ['INV20260501004', '优质纺织有限公司', '辅料采购',   3200.00,  3200.00,    0.00, now-timedelta(days=10), None,                   '正常',     '待付款', ''],
    ['INV20260501005', '明达印刷厂',       '吊牌印刷',   1800.00,  1500.00,  300.00, now-timedelta(days=40), now-timedelta(days=8),  '账期超时', '未付款', '账期已超40天，供应商催款'],
    ['INV20260501006', '捷运快递',         '快递服务',   9800.00,  9800.00,    0.00, now-timedelta(days=8),  None,                   '正常',     '待付款', ''],
    ['INV20260501007', '鑫源原材料',       '棉纱采购',  45000.00, 42000.00, 3000.00, now-timedelta(days=25), None,                   '对账差异', '未付款', '差异3000元，供应商坚持原价'],
    ['INV20260501008', '优品模具厂',       '模具费用',   8500.00,  8500.00,    0.00, now-timedelta(days=5),  None,                   '正常',     '待付款', ''],
    ['INV20260501009', '速达物流集团',     '配送费',     3600.00,     0.00, 3600.00, now-timedelta(days=45), None,                   '未开票',   '未付款', '发票至今未开，无法付款'],
    ['INV20260501010', '创新包装科技',     '礼盒包装',  15000.00, 14800.00,  200.00, now-timedelta(days=18), None,                   '对账差异', '待付款', '少发货200元'],
    ['INV20260501011', '全球认证机构',     '质检费',     2200.00,  2200.00,    0.00, now-timedelta(days=3),  None,                   '正常',     '待付款', ''],
    ['INV20260501012', '鑫源原材料',       '化纤采购',  32000.00,     0.00,    0.00, now-timedelta(days=50), None,                   '未开票',   '未付款', '合同金额32000，发票一直未开'],
    ['INV20260501013', '明达印刷厂',       '说明书印刷',  900.00,   900.00,    0.00, now-timedelta(days=7),  None,                   '正常',     '待付款', ''],
    ['INV20260501014', '优质纺织有限公司', '春季面料',  18500.00, 18500.00,    0.00, now-timedelta(days=32), now-timedelta(days=2),  '账期超时', '未付款', '超账期2天，财务未处理'],
    ['INV20260501015', '捷运快递',         '加急配送',      0.00,     0.00,    0.00, now-timedelta(days=2),  None,                   '金额异常', '未付款', '金额录入为0，疑似漏填'],
]
df4 = pd.DataFrame(supplier_data, columns=[
    '发票编号', '供应商名称', '采购类目', '发票金额', '对账金额', '差异金额',
    '开票日期', '付款日期', '账单状态', '付款状态', '备注'
])
df4.to_excel(os.path.join(desktop, '供应商对账表_示例.xlsx'), index=False)
print('done 4/4 供应商对账表')
print('ALL DONE')
