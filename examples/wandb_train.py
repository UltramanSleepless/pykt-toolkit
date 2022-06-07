import os
import argparse
import json

import sys
sys.path.append("../")

import torch
torch.set_num_threads(4) 
from torch.optim import SGD, Adam
import copy

from utils.utils import set_seed

from models.train_model import train_model
from models.evaluate_model import evaluate
from utils.utils import debug_print, init_model, init_dataset4train


os.environ['CUDA_LAUNCH_BLOCKING'] = "1"
device = "cpu" if not torch.cuda.is_available() else "cuda"
os.environ['CUBLAS_WORKSPACE_CONFIG']=':4096:2'

with open("../configs/wandb.json") as fin:
    wandb_config = json.load(fin)

import wandb
os.environ['WANDB_API_KEY'] = wandb_config["api_key"]
wandb.init(project="wandb_train")

def save_config(train_config, model_config, data_config, params, save_dir):
    d = {"train_config": train_config, 'model_config': model_config, "data_config": data_config, "params": params}
    save_path = os.path.join(save_dir, "config.json")
    with open(save_path, "w") as fout:
        json.dump(d, fout)

def main(params):
    model_name, dataset_name, fold, emb_type, save_dir = params["model_name"], params["dataset_name"], \
        params["fold"], params["emb_type"], params["save_dir"]
        
    debug_print(text = "load config files.",fuc_name="main")
    
    with open("../configs/kt_config.json") as f:
        config = json.load(f)
        train_config = config["train_config"]
        if model_name in ["dkvmn", "sakt", "saint", "akt", "atkt"]:
            train_config["batch_size"] = 64 ## because of OOM
        if model_name in ["gkt"]:
            train_config["batch_size"] = 16 
        model_config = copy.deepcopy(params)
        for key in ["model_name", "dataset_name", "emb_type", "save_dir", "fold", "seed"]:
            del model_config[key]
        # model_config = {"d_model": params["d_model"], "n_blocks": params["n_blocks"], "dropout": params["dropout"], "d_ff": params["d_ff"]}

    batch_size, num_epochs, optimizer = train_config["batch_size"], train_config["num_epochs"], train_config["optimizer"]
    seq_len = train_config["seq_len"]

    with open("../configs/data_config.json") as fin:
        data_config = json.load(fin)
    print("Start init data")
    print(dataset_name, model_name, data_config, fold, batch_size)
    
    debug_print(text = "init_dataset",fuc_name="main")
    train_loader, valid_loader, test_loader, test_window_loader = init_dataset4train(dataset_name, model_name, data_config, fold, batch_size)

    params_str = "_".join([str(_) for _ in params.values()])
    print(f"params: {params}, params_str: {params_str}")
    import uuid
    if not model_name in ['saint']:
        params_str = params_str+f"_{ str(uuid.uuid4())}"
    ckpt_path = os.path.join(save_dir, params_str)
    if not os.path.isdir(ckpt_path):
        os.makedirs(ckpt_path)
    print(f"Start training model: {model_name}, embtype: {emb_type}, save_dir: {ckpt_path}, dataset_name: {dataset_name}")
    print(f"model_config: {model_config}")
    print(f"train_config: {train_config}")

    save_config(train_config, model_config, data_config[dataset_name], params, ckpt_path)
    learning_rate = params["learning_rate"]
    del model_config["learning_rate"]
    if model_name in ["saint", "sakt"]:
        model_config["seq_len"] = seq_len
        
    debug_print(text = "init_model",fuc_name="main")
    model = init_model(model_name, model_config, data_config[dataset_name], emb_type)

    if optimizer == "sgd":
        opt = SGD(model.parameters(), learning_rate, momentum=0.9)
    elif optimizer == "adam":
        opt = Adam(model.parameters(), learning_rate)
   
    testauc, testacc = -1, -1
    window_testauc, window_testacc = -1, -1
    validauc, validacc = -1, -1
    best_epoch = -1
    save_model = True
    
    debug_print(text = "train model",fuc_name="main")
    
    testauc, testacc, window_testauc, window_testacc, validauc, validacc, best_epoch = train_model(model, train_loader, valid_loader, num_epochs, opt, ckpt_path, test_loader, test_window_loader, save_model)
    
    if save_model:
        best_model = init_model(model_name, model_config, data_config[dataset_name], emb_type)
        net = torch.load(os.path.join(ckpt_path, emb_type+"_model.ckpt"))
        best_model.load_state_dict(net)
        # evaluate test
        
        if test_loader != None:
            save_test_path = os.path.join(ckpt_path, emb_type+"_test_predictions.txt")
            testauc, testacc = evaluate(best_model, test_loader, model_name)#, save_test_path)
        if test_window_loader != None:
            save_test_path = os.path.join(ckpt_path, emb_type+"_test_window_predictions.txt")
            window_testauc, window_testacc = evaluate(best_model, test_window_loader, model_name)#, save_test_path)
        # window_testauc, window_testacc = -1, -1
        # trainauc, trainacc = self.evaluate(train_loader, emb_type)
        testauc, testacc, window_testauc, window_testacc = round(testauc, 4), round(testacc, 4), round(window_testauc, 4), round(window_testacc, 4)

    print("fold\tmodelname\tembtype\ttestauc\ttestacc\twindow_testauc\twindow_testacc\tvalidauc\tvalidacc\tbest_epoch")
    print(str(fold) + "\t" + model_name + "\t" + emb_type + "\t" + str(testauc) + "\t" + str(testacc) + "\t" + str(window_testauc) + "\t" + str(window_testacc) + "\t" + str(validauc) + "\t" + str(validacc) + "\t" + str(best_epoch))
    model_save_path = os.path.join(ckpt_path, emb_type+"_model.ckpt")
    wandb.log({"testauc": testauc, "testacc": testacc, "window_testauc": window_testauc, "window_testacc": window_testacc, 
                "validauc": validauc, "validacc": validacc, "best_epoch": best_epoch,"model_save_path":model_save_path})