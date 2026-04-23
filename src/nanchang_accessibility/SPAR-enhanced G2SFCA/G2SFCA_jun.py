import pandas as pd
import numpy as np

# =================配置参数=================
# 请确保以下文件名与您的实际文件名一致
origin_file = r'D:\Xia\比赛\论文2\3\3.1\origin2.txt'
destination_file = r'D:\Xia\比赛\论文2\3\3.1\des_jun.txt'
line_file = r'D:\Xia\比赛\论文2\3\3.1\lines1.txt'  # 请确保该文件在同一目录下
output_file = r'D:\Xia\比赛\论文2\3\3.1\Nanchang_SPAR_jun.csv'

beta = 30  # 高斯衰减参数，对应 30 分钟交通圈
# ==========================================

def calculate_g2sfca():
    print("🚀 正在读取数据...")
    # 读取数据，指定引擎防止中文路径问题
    df_origin = pd.read_csv(origin_file, encoding='utf-8')
    df_des = pd.read_csv(destination_file, encoding='utf-8')
    df_line = pd.read_csv(line_file, encoding='utf-8')

    print("🧩 正在解析 ID 并计算高斯权重...")
    
    # 修正错误点：使用 .str.split 和 .str.strip()
    # 兼容 "ID-ID" 和 "ID - ID" 两种格式
    ids = df_line['Name'].str.split('-', expand=True)
    df_line['O_ID'] = ids[0].str.strip()
    df_line['D_ID'] = ids[1].str.strip()

    # 确保时间字段是数值型
    df_line['Total_time_min'] = pd.to_numeric(df_line['Total_time_min'], errors='coerce')
    
    # 计算高斯衰减权重 G(t_ij)
    # 公式：G(t_ij) = exp(-(t_ij^2 / beta^2))
    df_line['G_weight'] = np.exp(-(df_line['Total_time_min']**2) / (beta**2))

    # --- 第一步：计算供给侧供需比 Rj ---
    print("📊 执行第一步：计算学校供需比 Rj...")
    
    # 统一 ID 为字符串类型，防止匹配失败
    df_origin['Name'] = df_origin['Name'].astype(str).str.strip()
    df_des['Name'] = df_des['Name'].astype(str).str.strip()

    # 关联格网需求量 (demand_jun)
    df_line = df_line.merge(df_origin[['Name', 'demand_jun']], 
                            left_on='O_ID', right_on='Name', how='left')
    
    # 计算每条线的加权需求量
    df_line['weighted_demand'] = df_line['demand_jun'] * df_line['G_weight']
    
    # 汇总每所学校的总负荷
    rj_denominator = df_line.groupby('D_ID')['weighted_demand'].sum().reset_index()
    rj_denominator.columns = ['D_ID', 'sum_weighted_demand']
    
    # 关联学校容量 (capacity)
    rj_df = rj_denominator.merge(df_des[['Name', 'capacity']], 
                                left_on='D_ID', right_on='Name', how='left')
    
    # 计算 Rj (每单位需求的资源量)
    rj_df['Rj'] = rj_df['capacity'] / rj_df['sum_weighted_demand']
    
    # 处理可能的除以 0 情况
    rj_df['Rj'] = rj_df['Rj'].replace([np.inf, -np.inf], 0).fillna(0)

    # --- 第二步：计算需求侧可达性 Ai ---
    print("📈 执行第二步：计算格网可达性 Ai...")
    
    # 将 Rj 关联回线表
    df_line = df_line.merge(rj_df[['D_ID', 'Rj']], on='D_ID', how='left')
    
    # 计算加权可达性
    df_line['weighted_Rj'] = df_line['Rj'] * df_line['G_weight']
    
    # 汇总每个格网点的可达性 Ai
    ai_result = df_line.groupby('O_ID')['weighted_Rj'].sum().reset_index()
    ai_result.columns = ['Grid_ID', 'Ai']

    # --- 第三步：标准化计算 SPAR ---
    print("⚖️ 计算标准化 SPAR 指数...")
    mean_ai = ai_result['Ai'].mean()
    if mean_ai == 0:
        print("❌ 警告：全市平均可达性为 0，请检查数据！")
        return

    ai_result['SPAR'] = ai_result['Ai'] / mean_ai

    # 4. 保存结果
    ai_result.to_csv(output_file, index=False)
    print("-" * 30)
    print(f"✅ 计算完成！结果已保存至: {output_file}")
    print(f"💡 全市平均可达性 (Ai 平均值): {mean_ai:.6f}")
    print(f"📝 共有 {len(ai_result)} 个格网点获得了 SPAR 结果。")

if __name__ == "__main__":
    calculate_g2sfca()