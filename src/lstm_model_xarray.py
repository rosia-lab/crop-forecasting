from math import sqrt
from tqdm import tqdm
import joblib
import warnings
warnings.filterwarnings('ignore')

from constants import FOLDER, S_COLUMNS, M_COLUMNS, G_COLUMNS

import numpy as np
import pandas as pd
import xarray as xr

import matplotlib.pyplot as plt

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, random_split
from torch.optim.lr_scheduler import ReduceLROnPlateau
from dataloader import DLDataset

from sklearn.metrics import r2_score

import wandb


DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
torch.cuda.empty_cache()


def main():
    wandb.init(
        project='winged-bull',
        config = {
            'batch_size': 64, # try 4, 8, 16, 32
            'hidden_size':128, # try 128 to 512
            'num_layers': 2, # try 1 to 4
            'learning_rate': 1e-3,
            'dropout': 0.1,
            'epochs': 5000,
            'optimizer': 'AdamW', # try AdamW, LBFGS 
            'criterion': 'MSELoss', # try MSELoss, L1Loss, HuberLoss
            'val_rate': 0.2
        }
    )

    train_loader, val_loader, test_loader = get_loaders(wandb.config, num_workers=4)
    first_batch = train_loader.dataset[0]
    
    wandb.config['s_num_features'] = first_batch['s_input'].shape[1]
    wandb.config['m_num_features'] = first_batch['m_input'].shape[1]
    wandb.config['g_in_features'] = first_batch['g_input'].shape[0]
    wandb.config['c_in_features'] = 2 * (wandb.config['hidden_size'] - 2) + wandb.config['g_in_features']

    model = LSTMModel(wandb.config)
    model.to(DEVICE)
    
    criterion = get_criterion(wandb.config)
    optimizer = torch.optim.AdamW(model.parameters(), lr=wandb.config['learning_rate'])
    scheduler = ReduceLROnPlateau(optimizer, patience=500)
    
    train_model(wandb.config, model, optimizer, scheduler, criterion, train_loader, val_loader)
    make_submission(model, test_loader)
    

def get_loaders(config, num_workers):
    batch_size = config['batch_size']
    val_rate = config['val_rate']

    dataset_path = f'../data/processed/{FOLDER}/train_filter_processed.nc'
    xdf = xr.open_dataset(dataset_path, engine='scipy')
    dataset = DLDataset(xdf.copy(deep=True))
    
    val_size = int(val_rate * dataset.__len__)
    train_size = dataset.__len__ - val_size
    
    generator = torch.Generator()
    train_dataset, val_dataset = random_split(dataset, [train_size, val_size], generator=generator)
    train_loader = DataLoader(train_dataset, shuffle=True, batch_size=batch_size, num_workers=num_workers)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, num_workers=num_workers)

    dataset_path = f'../data/processed/{FOLDER}/test_filter_processed.nc'
    xdf = xr.open_dataset(dataset_path, engine='scipy')
    test_dataset = DLDataset(xdf.copy(deep=True))
    
    test_loader = DataLoader(test_dataset, batch_size=1, num_workers=num_workers)
    
    return train_loader, val_loader, test_loader


def get_criterion(config):
    if config['criterion'] == 'MSELoss':
        criterion = nn.MSELoss()
    elif config['criterion'] == 'L1Loss':
        criterion = nn.L1Loss()
    elif config['criterion'] == 'HuberLoss':
        criterion = nn.HuberLoss()
        
    return criterion


class LSTMModel(nn.Module):
    def __init__(self, config):
        super(LSTMModel, self).__init__()
        self.hidden_size = config['hidden_size']
        self.num_layers = config['num_layers']
        self.dropout = config['dropout']

        self.s_num_features = config['s_num_features']
        self.m_num_features = config['m_num_features']
        # self.g_in_features = config['g_in_features']
        self.c_in_features = config['c_in_features']
        
        self.s_lstm = nn.LSTM(self.s_num_features, self.hidden_size, self.num_layers, batch_first=True)
        self.m_lstm = nn.LSTM(self.m_num_features, self.hidden_size, self.num_layers, batch_first=True)
        self.bn_lstm = nn.BatchNorm1d(self.hidden_size)
        
        self.cnn = nn.Conv1d(1, 1, kernel_size=3)
        self.bn_cnn = nn.BatchNorm1d(self.hidden_size - 2) # because kernel_size = 3
        
        # self.g_linear = nn.Linear(self.g_in_features, self.g_in_features)
        # self.g_bn = nn.BatchNorm1d(self.g_in_features)
        
        self.c_linear_1 = nn.Linear(self.c_in_features, 4*self.c_in_features)
        self.c_linear_2 = nn.Linear(4*self.c_in_features, 4*self.c_in_features)
        self.c_linear_3 = nn.Linear(4*self.c_in_features, 2*self.c_in_features)
        self.c_linear_4 = nn.Linear(2*self.c_in_features, 2*self.c_in_features)
        self.c_linear_5 = nn.Linear(2*self.c_in_features, self.c_in_features)
        self.c_linear_6 = nn.Linear(self.c_in_features, 1)
        
        self.tanh = nn.Tanh()
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(self.dropout)

    def forward(self, x):
        s_input = x['s_input']
        m_input = x['m_input']
        g_input = x['g_input']
        
        # Spectral LSTM
        s_h0 = torch.zeros(self.num_layers, s_input.size(0), self.hidden_size).requires_grad_().to(DEVICE)
        s_c0 = torch.zeros(self.num_layers, s_input.size(0), self.hidden_size).requires_grad_().to(DEVICE)
        
        s_output, _ = self.s_lstm(s_input, (s_h0, s_c0))        
        s_output = self.bn_lstm(s_output[:, -1, :])
        s_output = self.tanh(s_output)
        s_output = self.dropout(s_output)
        
        # Meteo LSTM
        m_h0 = torch.zeros(self.num_layers, m_input.size(0), self.hidden_size).requires_grad_().to(DEVICE)
        m_c0 = torch.zeros(self.num_layers, m_input.size(0), self.hidden_size).requires_grad_().to(DEVICE)
        m_output, _ = self.m_lstm(m_input, (m_h0, m_c0))        
        m_output = self.bn_lstm(m_output[:, -1, :])
        m_output = self.tanh(m_output)
        m_output = self.dropout(m_output)
        
        # Spectral Conv1D
        s_output = torch.unsqueeze(s_output, 1) # (batch_size, num_layers) to (batch_size, 1, num_layers)        
        s_output = self.cnn(s_output)
        s_output = torch.squeeze(s_output) # (batch_size, 1, num_layers - 2) to (batch_size, num_layers - 2)           
        s_output = self.bn_cnn(s_output)
        s_output = self.relu(s_output)
        s_output = self.dropout(s_output)
        
        # Meteo Conv1D
        m_output = torch.unsqueeze(m_output, 1)    
        m_output = self.cnn(m_output)
        m_output = torch.squeeze(m_output)        
        m_output = self.bn_cnn(m_output)
        m_output = self.relu(m_output)
        m_output = self.dropout(m_output)
        
        # # Geo FC
        # g_output = self.g_linear(g_input)
        # g_output = self.g_bn(g_output)
        # g_output = self.relu(g_output)
        # g_output = self.dropout(g_output)
        
        # Concatanate inputs
        c_input = torch.cat((s_output, m_output, g_input), 1)
        c_output = self.c_linear_1(c_input)
        c_output = self.relu(c_output)
        c_output = self.dropout(c_output)
        c_output = self.c_linear_2(c_output)
        c_output = self.relu(c_output)
        c_output = self.dropout(c_output)
        c_output = self.c_linear_3(c_output)
        c_output = self.relu(c_output)
        c_output = self.dropout(c_output)
        c_output = self.c_linear_4(c_output)
        c_output = self.relu(c_output)
        c_output = self.dropout(c_output)
        c_output = self.c_linear_5(c_output)
        c_output = self.relu(c_output)
        c_output = self.dropout(c_output)
        output = self.c_linear_6(c_output)
        
        return output
    
    
def train_epoch(model, optimizer, criterion, train_loader):
    train_loss = 0
    
    for data in train_loader:
        keys_input = ['s_input', 'm_input', 'g_input']
        inputs = {key: data[key].to(DEVICE) for key in keys_input}
        labels = data['labels'].float().to(DEVICE)

        optimizer.zero_grad()
        outputs = model(inputs)
        
        loss = criterion(outputs, labels)
        train_loss += loss.item()
        loss.backward()
        
        optimizer.step()
        
    train_loss /= len(train_loader)
    
    return train_loss


def val_epoch(model, criterion, val_loader):
    val_loss = 0
    val_labels = []
    val_preds = []
    
    for data in val_loader:
        keys_input = ['s_input', 'm_input', 'g_input']
        inputs = {key: data[key].to(DEVICE) for key in keys_input}
        labels = data['labels'].float().to(DEVICE)

        outputs = model(inputs)
        
        loss = criterion(outputs, labels)
        val_loss += loss.item()
        
        val_labels += labels.tolist()
        val_preds += outputs.tolist()
        
    val_loss /= len(val_loader)
    val_r2_score = r2_score(val_labels, val_preds)
        
    return val_loss, val_r2_score


def early_stopping():
    return True


def train_model(config, model, optimizer, scheduler, criterion, train_loader, val_loader):
    epochs = config['epochs']
    train_losses = []
    val_losses = []
    
    model.train()
    for epoch in range(epochs):
        print(f'\n--- EPOCH {epoch+1}/{epochs} ---')
        train_loss = train_epoch(model, optimizer, criterion, train_loader)
        train_losses.append(train_loss)

        val_loss, val_r2_score = val_epoch(model, criterion, val_loader)
        scheduler.step(val_loss)
        val_losses.append(val_loss)

        wandb.log({'train_loss': train_loss, 'val_loss': val_loss, 'val_r2_score': val_r2_score})
        print(f'Train = {train_loss:.5f} - Val = {val_loss:.5f} - Val R2 = {val_r2_score:.5f}')

        
def round_prediction():
    return True


def make_submission(model, test_loader):
    print('\nCreate submission.csv')
    test_path = '../data/raw/test.csv'
    test_df = pd.read_csv(test_path)
    
    model.eval()
    with torch.no_grad():
        for data in test_loader:
            keys_input = ['s_input', 'm_input', 'g_input']
            inputs = {key: data[key].to(DEVICE) for key in keys_input}

            district = data['district'][0]
            latitude = data['latitude'].item()
            longitude = data['longitude'].item()
            date_of_harvest = data['date_of_harvest'][0]

            output = model(inputs)

            test_df.loc[(test_df['District'] == district) &
                        (test_df['Latitude'] == latitude) &
                        (test_df['Longitude'] == longitude) &
                        (test_df['Date of Harvest'] == date_of_harvest),
                        'Predicted Rice Yield (kg/ha)'] = output.item()

    label_scaler = joblib.load(f'../data/processed/lstm/{FOLDER}/scaler_t.joblib')
    test_df['Predicted Rice Yield (kg/ha)'] = label_scaler.inverse_transform(test_df[['Predicted Rice Yield (kg/ha)']])
    test_df.to_csv('submission.csv', index=False)
        
    
if __name__ == '__main__':
    main()