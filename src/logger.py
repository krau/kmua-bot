import logging,os


class Logger:
    def __init__(self, name: str, show: bool, save: bool = True, debug: bool = False) -> None:
        normal_log_path = f'logs/normal.log'
        debug_log_path = f'logs/debug.log'
        if not os.path.exists('./logs'):
            os.mkdir('./logs')
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        self.formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s: - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        if not self.logger.handlers:
            if show:
                sh = logging.StreamHandler()
                if debug:
                    sh.setLevel(logging.DEBUG)
                else:
                    sh.setLevel(logging.INFO)
                sh.setFormatter(self.formatter)
                self.logger.addHandler(sh)
            if save:
                fh_debug = logging.FileHandler(debug_log_path)
                fh_debug.setLevel(logging.DEBUG)
                fh_debug.setFormatter(self.formatter)
                fh = logging.FileHandler(normal_log_path)
                fh.setLevel(logging.INFO)
                fh.setFormatter(self.formatter)
                self.logger.addHandler(fh)
                self.logger.addHandler(fh_debug)

    def debug(self, message):
        self.logger.debug(message)

    def info(self, message):
        self.logger.info(message)

    def warn(self, message):
        self.logger.warning(message)

    def error(self, message):
        self.logger.error(message)

    def critical(self, message):
        self.logger.critical(message)
