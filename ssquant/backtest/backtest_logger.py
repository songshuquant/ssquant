import os
from datetime import datetime

class BacktestLogger:
    """回测日志管理器类，负责处理日志记录、日志文件创建等功能"""
    
    def __init__(self, debug_mode=True):
        """初始化日志管理器"""
        self.log_file = None
        self.performance_file = None
        self.debug_mode = debug_mode
    
    def set_debug_mode(self, debug_mode):
        """设置调试模式
        
        Args:
            debug_mode: 是否开启调试模式
        """
        self.debug_mode = debug_mode
    
    def prepare_log_file(self, symbols_and_periods):
        """准备日志文件
        
        Args:
            symbols_and_periods: 品种和周期列表
            
        Returns:
            log_file_path: 日志文件路径
        """
        # 检查是否禁用可视化和日志
        if os.environ.get('NO_VISUALIZATION', '').lower() == 'true':
            # 在参数优化过程中禁用日志文件
            self.log_file = None
            self.performance_file = None
            return None
            
        # 创建日志目录
        log_dir = "backtest_logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        # 创建日志文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        symbols_str = "_".join([item["symbol"] for item in symbols_and_periods])
        self.log_file = os.path.join(log_dir, f"backtest_{symbols_str}_{timestamp}.log")
        
        # 创建综合绩效报告文件 - 即使在debug=False模式下也创建
        results_dir = "backtest_results"
        if not os.path.exists(results_dir):
            os.makedirs(results_dir)
        self.performance_file = os.path.join(results_dir, f"performance_{symbols_str}_{timestamp}.txt")
        
        # 写入日志头
        with open(self.log_file, 'w', encoding='utf-8') as f:
            f.write(f"多数据源回测日志 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"回测品种: {symbols_str}\n")
            f.write("-" * 80 + "\n\n")
            
        return self.log_file
    
    def log_message(self, message):
        """记录日志消息
        
        Args:
            message: 日志消息
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        
        # 检查是否禁用控制台日志
        if self.debug_mode and not os.environ.get('NO_CONSOLE_LOG', '').lower() == 'true':
            print(log_message)  # 打印到控制台
        
        # 如果有日志文件，并且未禁用日志，则写入
        # 即使在debug=False模式下也写入关键日志信息
        if self.log_file and not os.environ.get('NO_VISUALIZATION', '').lower() == 'true':
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_message + "\n")
    
    def get_performance_file(self):
        """获取绩效报告文件路径"""
        # 如果禁用可视化，则返回None
        if os.environ.get('NO_VISUALIZATION', '').lower() == 'true':
            return None
        
        # 确保绩效报告文件目录存在
        if self.performance_file and not os.path.exists(os.path.dirname(self.performance_file)):
            os.makedirs(os.path.dirname(self.performance_file))
            
        return self.performance_file 