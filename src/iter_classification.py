import argparse
import os
import random
import time
import sys

import numpy as np
from tqdm import tqdm
import torch
import torch.backends.cudnn as cudnn
import torch.optim as optim
from torch.utils.tensorboard import SummaryWriter

from src import myutils
from src.dataset_interface import DataInterface
from src.model import Net

# Set Seed
torch.manual_seed(1234)
np.random.seed(1234)
random.seed(1234)


def parser(feed_by_lst=None):
    '''
    argument
    '''
    parser = argparse.ArgumentParser(description='PyTorch training')
    parser.add_argument('--datapath', '-dp', type=str, default="./data",  # relative path by exec/
                        help='Data downloaded directory')
    parser.add_argument('--task', '-t', type=str, default="MNIST",
                        help='Classification dataset')
    parser.add_argument('--threading', '-thr', type=int, default=5,
                        help='CPU thread number for data loading')
    parser.add_argument('--epochs', '-e', type=int, default=5,
                        help='number of epochs to train (default: 2)')
    parser.add_argument('--lr', '-lr', type=float, default=1e-4,
                        help='learning rate (default: 0.01)')
    parser.add_argument('--batch', '-b', type=int, default=512,
                        help='batch size (default: 0.01)')
    parser.add_argument('--logdir', '-log', type=str, default="./log",
                        help='log directory (default: ./log)')
    parser.add_argument('--span', '-s', type=int, default=1,
                        help='log directory (default: 1)')
    parser.add_argument('--restore_path', '-r', type=str, default="",
                        help='Directory to restore the model')
    if feed_by_lst is not None:
        args = parser.parse_args(feed_by_lst)
    else:
        args = parser.parse_args()
    return args


def train_classification(net, dataloaders_dict: dict, criterion, optimizer, num_epochs, logpath, start_epoch=0, save_span=1):
    writer = SummaryWriter(logpath)  # Create Tensorboard  summary writer
    start_time = time.time()

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print("Use device : ", device)

    # ネットワークをGPUへ
    net.to(device)
    if start_epoch != 0:
        # If saved model,
        print('Restart Option')
        for state in optimizer.state.values():
            for k, v in state.items():
                if isinstance(v, torch.Tensor):
                    state[k] = v.to(device)
        pass

    # ネットワークがある程度固定であれば、高速化させる
    # cudnn.benchmark = True
    cudnn.benchmark = False

    best_acc = 0

    acc_dict = {
        "train": 0,
        "val": 0,
    }

    # epochのループ
    last_epoch_fin = time.time()
    for epoch in range(num_epochs + 1):
        if epoch < start_epoch:
            print('Skip until ' + str(start_epoch) + " (now:" + str(epoch) + ")")
            last_epoch_fin = time.time()
            continue
            pass
        epoch_train_corrects = 0  # epochの正解数
        epoch_train_loss = 0.0
        epoch_val_corrects = 0  # epochの正解数
        epoch_val_loss = 0.0

        print('-------------')
        print('Epoch {}/{}'.format(epoch, num_epochs))

        # epochごとの訓練と検証のループ
        for phase in ['train', 'val']:
            correct = 0
            total = 0
            phase_str = phase
            if ((epoch - start_epoch) == 0) and (phase == 'train'):
                print("As the first step, Optimization will NOT be done")
                phase_str += " = NO BACKWARD ="
                pass
            elif ((epoch - start_epoch) == 1) and (phase == 'train'):
                print("Start optimization ...")
                pass
            else:
                pass
            with tqdm(total=len(dataloaders_dict[phase])) as pbar:
                pbar.set_description(f"Epoch[{epoch}/{num_epochs}] ({phase_str})")
                # データローダーからminibatchずつ取り出すループ
                for inputs, labels in dataloaders_dict[phase]:
                    if inputs.size()[0] == 1:
                        print('batch == 1 induce batch-norm error, so will be skipped')
                        continue

                    if phase == 'train':
                        net.train()  # モデルを訓練モードに
                        optimizer.zero_grad()

                    else:
                        net.eval()  # モデルを検証モードに

                    # GPUが使えるならGPUにデータを送る
                    imges = inputs.to(device)
                    labels = labels.to(device)

                    # 順伝搬（forward）計算
                    with torch.set_grad_enabled(phase == 'train'):
                        outputs = net(imges)
                        loss = criterion(outputs, labels)
                        _, preds = torch.max(outputs.data, 1)  # ラベルを予測
                        total += labels.size(0)
                        correct += (preds == labels).sum().item()

                        # 訓練時はバックプロパゲーション
                        if phase == 'train':
                            if ((epoch - start_epoch) == 0):
                                pass
                            else:
                                loss.backward()  # 勾配の計算
                                optimizer.step()  # Update of Adam optimaizer
                            epoch_train_loss += loss.item() * inputs.size(0)  # Scalar値の抽出k関数==item()
                            epoch_train_corrects += torch.sum(preds == labels.data)
                        else:
                            epoch_val_loss += loss.item() * inputs.size(0)
                            epoch_val_corrects += torch.sum(preds == labels.data)
                            pass
                        pass
                    pbar.update(1)
                    pass  # Minibatch end

            acc_dict[phase] = float(correct / total) * 100.
            pass  # Phase end
        epoch_train_percent = acc_dict["train"]
        epoch_val_percent = acc_dict["val"]

        # epochごとのlossと正解率を表示
        print("Train : Loss: {:.2f} Acc: {:.2f}".format(epoch_train_loss, epoch_train_percent))
        print("Valid : Loss: {:.2f} Acc: {:.2f}".format(epoch_val_loss, epoch_val_percent))
        now_best = False
        if best_acc > epoch_val_percent:
            now_best = True
            best_acc = epoch_val_percent
            pass  # End save

        # Summary Writerへ書き込み
        writer.add_scalar("train/acc", epoch_train_percent, epoch)
        writer.add_scalar("val/acc", epoch_val_percent, epoch)

        # 最後のネットワークを保存する
        if epoch % save_span == 0:
            print('Log Writing ...')
            state = {
                "epoch": epoch,
                "state_dict": net.state_dict(),
                "optimizer": optimizer.state_dict(),
            }
            myutils.save_checkpoint(state=state, is_best=now_best, save_path=logpath,
                                    filename=myutils._CHECKPOINT_PREFIX + str(epoch).zfill(
                                        4) + myutils._CHECKPOINT_SUFFIX)
            pass  # End
        print('Elapsed time {:.2f}[s] (epoch: {})'.format(time.time() - last_epoch_fin, epoch))
        last_epoch_fin = time.time()
        pass  # End epoch
    print("Total elapsed : {:.2f}[s]".format(time.time() - start_time))
    pass


class TrainingIter(object):
    def __init__(self, args:argparse.Namespace):
        self.dataloaders_dict, self.log_path, self.model, \
        self.criterion, self.optimizer, self.max_epoch, self.save_span, self.restore_path = self._parser2config(args)
        self.log = args.logdir
        pass

    def _parser2config(self, args_: argparse.Namespace):
        # max epoch
        max_epoch = args_.epochs

        # Call training data
        data_path = args_.datapath
        task = args_.task
        batch_size = args_.batch
        num_works = args_.threading
        dls = DataInterface(root_path=data_path, dataset=task, batch_size=batch_size, num_works=num_works)
        dataloaders_dict = dls.dataloader_dict()

        # Log directory creation
        log = args_.logdir
        log_path = myutils.timestamped_path(log)

        # Def model
        net = Net()

        # Def optimizer
        criterion = torch.nn.CrossEntropyLoss()

        # Set optimizer
        lr = args_.lr
        optimizer = optim.Adam(net.parameters(), lr=lr)

        # Set save span
        span_ = args_.span

        # Set load model if you specified
        restore_ = args_.restore_path

        return dataloaders_dict, log_path, net, criterion, optimizer, max_epoch, span_, restore_

    def run(self):
        train_classification(net=self.model, dataloaders_dict=self.dataloaders_dict, criterion=self.criterion,
                             optimizer=self.optimizer, logpath=self.log_path, num_epochs=self.max_epoch, )
        pass

    def restart(self, load_logpath=""):
        resore_path = load_logpath if load_logpath != "" else self.restore_path
        if not self.restore_path == "":
            model_, optimizer_, epoch_ = myutils.load_checkpoint(model=self.model, optimizer=self.optimizer,
                                                             filename= self.restore_path)
            train_classification(net=model_, dataloaders_dict=self.dataloaders_dict, criterion=self.criterion,
                             num_epochs=self.max_epoch,
                             optimizer=optimizer_, logpath=self.log_path, start_epoch=epoch_)
        else:
            print("[ERROR] Set restore model path by the argumrent --restore ")
            sys.exit()
            pass

    def get_load_weight(self, yd: str, epoch: int, hms="", zero_fill=4):
        date_ = myutils.get_timestamped_weight_path(yd=yd, hms=hms, epoch=epoch, zero_fill=zero_fill)
        self.restore_path = os.path.join(self.log, date_)
        return self.restore_path
        # pass
