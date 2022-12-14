# -*- coding: utf-8 -*-
"""SHL.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1UkVnDMAhsyhHoODZt4a_-bHpaRWPGIb_

## Loading Dataset and dependencies
"""

!pip install transformers
!pip install optuna

from torch.utils.tensorboard import SummaryWriter
writer = SummaryWriter()

import pandas as pd
import statistics
import numpy as np
import os
import matplotlib.pyplot as plt
import optuna
import torch
import torch.nn.functional as F
from torchsummary import summary
from tqdm import tqdm
import transformers
import torch.nn as nn
from torch.utils.data import Dataset , DataLoader , RandomSampler, SequentialSampler
from transformers import BertForSequenceClassification , AdamW
import time
from transformers import get_linear_schedule_with_warmup
from sklearn.metrics import f1_score , precision_score, confusion_matrix
from torch import optim

#from google.colab import drive
#drive.mount('/content/drive')

#!ls "/content/drive"

#path = "/content/drive/MyDrive/NLP Assignment"
train_df = pd.read_csv(os.path.join(path,"train_data.csv"))

val_df = pd.read_csv(os.path.join(path,"val_data.csv"))

test_df = pd.read_csv(os.path.join(path,"test_data.csv"))

"""## Some EDA"""

print("Number of Null values in training set is : ",train_df.isnull().sum().sum())
print("Number of Null values in validation set is : ",val_df.isnull().sum().sum())

train_df['labels'].value_counts().plot.bar()
plt.title("distribution of train labels")

val_df['labels'].value_counts().plot.bar()
plt.title("distribution of val labels")

print('Average word length of texts in train dataset is {0:.0f}.'.format(np.mean(train_df['input'].apply(lambda x: len(x.split())))))
print('Max word length of texts in train dataset is {0:.0f}.'.format(np.max(train_df['input'].apply(lambda x: len(x.split())))))

print('Average word length of texts in val dataset is {0:.0f}.'.format(np.mean(val_df['input'].apply(lambda x: len(x.split())))))
print('Max word length of texts in val dataset is {0:.0f}.'.format(np.max(val_df['input'].apply(lambda x: len(x.split())))))

plt.hist(train_df['input'].apply(lambda x: len(x.split())),bins=[0,4,8,10,15,20,25,35,50,100,200])
plt.title('Distribution of  text length in training set')

plt.hist(val_df['input'].apply(lambda x: len(x.split())),bins=[0,4,8,10,15,20,25,35,50,100,200])
plt.title('Distribution of  text length in val set')

"""## Making the Model"""

# If there's a GPU available...
if torch.cuda.is_available():

    # Tell PyTorch to use the GPU.
    device = torch.device("cuda")

    print('There are %d GPU(s) available.' % torch.cuda.device_count())

    print('We will use the GPU:', torch.cuda.get_device_name(0))

# If not...
else:
    print('No GPU available, using the CPU instead.')
    device = torch.device("cpu")

class BERTDataset(Dataset):
  def __init__(self,tokenizer,max_length,df,Test=False):
    super(Dataset,self).__init__()
    self.tokenizer = tokenizer
    self.max_length = max_length
    if not Test:
      self.target = df.iloc[:,1]
    self.df = df
    self.Test = Test

  def __len__(self):
    return len(self.df)

  def __getitem__(self,index):

    text = self.df.iloc[index,0]

    input = self.tokenizer.encode_plus(
        text,
        None,
        padding='max_length',
        truncation= True,
        add_special_tokens=True,
        return_attention_mask=True,
        max_length = self.max_length,
    )
    ids = input['input_ids']
    token_type_ids = input['token_type_ids']
    mask = input['attention_mask']

    if self.Test:
      return {
          'ids': torch.tensor(ids,dtype=torch.long),
          'mask':torch.tensor(mask,dtype=torch.long),
          'token_type_id': torch.tensor(token_type_ids,dtype=torch.long),
          #'target': torch.tensor(self.df.iloc[index, 1], dtype=torch.long),
          #'original_text' : self.df.iloc[index,0] I just added this to see how it changes
      }
    else:
      return {
        'ids': torch.tensor(ids,dtype=torch.long),
        'mask':torch.tensor(mask,dtype=torch.long),
        'token_type_id': torch.tensor(token_type_ids,dtype=torch.long),
        'target': torch.tensor(self.df.iloc[index, 1], dtype=torch.long),
        #'original_text' : self.df.iloc[index,0] I just added this to see how it changes
    }

BATCH_SIZE = 8

tokenizer = transformers.BertTokenizer.from_pretrained("bert-base-uncased")

train_dataset= BERTDataset(tokenizer,325,train_df) ## Here I have used a max_length for the embedding vector set to 350, to be on the safer side.
val_dataset = BERTDataset(tokenizer,325,val_df)
test_dataset = BERTDataset(tokenizer,325,test_df,Test=True)

train_dataloader=DataLoader(
    dataset=train_dataset,
    sampler = RandomSampler(train_dataset),
    batch_size=BATCH_SIZE,
    num_workers=2)
val_dataloader = DataLoader(
    dataset=val_dataset,
    sampler = SequentialSampler(val_dataset),
    batch_size=BATCH_SIZE)
test_dataloader = DataLoader(
    dataset=test_dataset,
    sampler = SequentialSampler(test_dataset),
    batch_size=BATCH_SIZE)

class BERTModel(nn.Module):
  def __init__(self):
    super(BERTModel, self).__init__()

    self.bert = BertForSequenceClassification.from_pretrained(
        "bert-base-uncased",
        num_labels=2,
        output_attentions=False,
        output_hidden_states=False
        )
    #self.softmax = nn.Softmax()
  def forward(self,ids,
                      token_type_ids,
                      attention_mask,
                      labels=None):
    x = self.bert(ids,token_type_ids,attention_mask)
    x = torch.sigmoid(x.logits)
    return x
model = BERTModel()
model.to(device)

## Essentially using the last classifier to train. As the dataset provided is in English and BERT is trained heavily
'''
for name,params in model.named_parameters():
  if 'classifier' not in name:
    params.requires_grad = False
    '''

params = list(model.named_parameters())

print("Printing the last 3 layers weights and biases and dimensions of the 12 layer BERT pretrained model")

for p in params[-3:]:
  print(f" Layer name is {p[0]}, and the size of its parameters space is {p[1].size()}")

print("As you can see, The last layer is a classifier for 2 labels")

epochs = 3

total_steps = len(train_dataloader) * epochs

optimizer = optim.AdamW(model.parameters(), lr=1e-3)
scheduler = get_linear_schedule_with_warmup(optimizer,
                                            num_warmup_steps = 0,
                                            num_training_steps = total_steps)
loss = nn.BCELoss()

def calculate_acc(pred,labels):
  labels = labels.numpy()
  pred = pred.numpy()
  pred_new = np.argmax(pred,axis=1).flatten() ## gets the maximum likelihood from 2 labels
  labels_new = labels.flatten()
  return np.sum(pred_new == labels_new) / len(pred_new) #compares the accuracy

a = torch.tensor([[1,2,3],[3,4,7]])
ind = torch.amax(a,dim=1)
print(ind.flatten())
#a[ind]

def convert_to_logits(pred):
  #labels = labels.numpy()
  #pred = pred.numpy()
  pred_new = torch.amax(pred,dim=1).flatten()
  return torch.tensor(pred_new)

def get_pred(pred):
  pred = pred.numpy()
  pred_new = np.argmax(pred,axis=1).flatten()
  return pred_new

def train(dataloader,model,optimizer,scheduler,epoch,criterion):
  print("Training for this epoch")
  train_loss = 0
  t0 = time.time()
  model.train()
  for step,batch in enumerate(dataloader):
    if step % 50 == 0 and step != 0:
        t2 = time.time()
        print(f"Time elapsed for {step} batch is : {t2-t0}")

    input_ids = batch['ids'].to(device)
    token_ids = batch['token_type_id'].to(device)
    mask = batch['mask'].to(device)
    target = batch['target'].to(device)

    model.zero_grad()

    output = model(input_ids,
                        token_type_ids=token_ids,
                        attention_mask=mask)
    #loss = output.loss
    #logits = output.logits
    #print(f"The logits are {logits} and the size is {logits.size}")
    #print("The labels are {labels} and the size is {labels.size}")
    #output = output.detach().cpu()
    loss = criterion(convert_to_logits(output).type(torch.float).to(device),target.type(torch.float))
    train_loss += loss
    print(f"Train loss for epoch {epoch} and batch number {step} is {loss}")
    loss.requires_grad = True
    loss.backward()


    optimizer.step()
    scheduler.step()
  t1 = time.time()
  print(f"Epoch {epoch} done...")
  print(f"time taken for training epoch number {epoch} is {t1-t0}")
  print(f"Average loss for one epoch number {epoch} is {train_loss / len(dataloader)}")
  return train_loss / len(dataloader) , t1-t0

def eval(dataloader,model,epoch,criterion,Test=False):

  t0 = time.time()
  model.eval()

  eval_accuracy = 0
  eval_loss = 0
  results = []
  if not Test:
    for step,batch in enumerate(dataloader):

      if step % 50 == 0 and step != 0:
        t2 = time.time()
        print(f"Time elapsed for {step} batch is : {t2-t0}")
        print(f"accuracy for batch {step} is {eval_accuracy}")

      input_ids = batch['ids'].to(device)
      token_ids = batch['token_type_id'].to(device)
      mask = batch['mask'].to(device)
      target = batch['target'].to(device)

      with torch.no_grad():
        output = model(input_ids,
                            token_type_ids=token_ids,
                            attention_mask=mask,)
      #loss = output.loss
      #logits = output.logits
      #output = output.detach().cpu()
      loss = criterion(convert_to_logits(output).type(torch.float).to(device),target.type(torch.float))

      eval_loss += loss
      print(f"Eval loss for epoch {epoch} and batch number {step} is {eval_loss}")


      accuracy = calculate_acc(output.detach().cpu(),target.detach().to('cpu'))
      eval_accuracy += accuracy

    t1 = time.time()
    print(f"time taken for evaluating epoch number {epoch} is {t1-t0}")
    print(f"Average Eval loss for epoch number {epoch} is {eval_loss / len(dataloader)}")
    print(f"Average accuracy for epcoh number {epoch} is {eval_accuracy/len(dataloader)}")
    return eval_loss / len(dataloader), eval_accuracy/len(dataloader) , t1-t0
  else:
    for step,batch in enumerate(dataloader):
      input_ids = batch['ids'].to(device)
      token_ids = batch['token_type_id'].to(device)
      mask = batch['mask'].to(device)

      with torch.no_grad():
        output = model(input_ids,
                            token_type_ids=token_ids,
                            attention_mask=mask,
                            )
      #logits = output.logits
      output = output.detach().cpu()
      pred = get_pred(output)
      results += pred.tolist()
    return results

def train_mode():
  train_stats = []
  #optimizer = params['optimizer']

  for epoch in range(epochs):
    print(f"Training for {epoch} epoch")
    print("Training ...")
    avg_train_loss , train_time = train(train_dataloader,model,optimizer,scheduler,epoch,loss)
    writer.add_scalar("Loss/train", avg_train_loss, epoch)
    print("Evaluating on validation set ...")
    avg_val_loss, avg_accuracy, eval_time = eval(val_dataloader,model,epoch,loss)
    writer.add_scalar("Loss/train", avg_val_loss, epoch)
    train_stats.append({
        'epoch': epoch+1,
        'train_loss': avg_train_loss,
        'val_loss': avg_val_loss,
        'val_accuracy': avg_accuracy,
        'train_time': train_time,
        'eval_time':eval_time
    })
  return train_stats

# Optimizing with optuna
'''
def objective(trial):
  optimizer = trial.suggest_categorical('optimizer',['AdamW','Adam','RMSprop','SGD'])
  lr =  trial.suggest_float('lr',2e-5,1e-1)
  opti = getattr(optim,optimizer)(model.parameters(),lr=lr)
  params = {
      "optimizer": opti,
      "lr" : lr
  }
  train_stats = train_mode(params)
  eval_loss_avg = statistics.mean([d['val_loss'] for d in train_stats])
  return eval_loss_avg
 


study = optuna.create_study(direction='minimize')
study.optimize(objective,n_trials=2)


print("Best Trial:")
trial_ = study.best_trial # This saves the best trial(Essential which hyperparameters gave)

print(trial_.values)
print(trial_.params)
'''

torch.cuda.memory_summary(device=device, abbreviated=False)

#training the model
train_stats = train_mode()

!pip install tensorboard

tensorboard --logdir=runs

df_summary = pd.DataFrame(data=train_stats)
df_summary = df_summary.set_index('epoch')
df_summary

df_summary['train_loss'] = df_summary['train_loss'].apply(lambda x : x.detach().cpu().numpy().tolist())
#df_summary['val_loss'] = df_summary['val_loss'].apply(lambda x : x.detach().cpu().numpy().tolist())

df_summary

a= np.array([1,2,3])
b = np.array([1,2,4])

df_summary.to_csv("summary of train.csv")

import seaborn as sns
sns.set(style='darkgrid')

sns.set(font_scale=1.5)
plt.rcParams["figure.figsize"] = (12,6)


plt.plot(df_summary['train_loss'], 'b-o', label="training")
plt.plot(df_summary['val_loss'], 'g-o', label="Validation")


plt.title("Loss of training and validation")
plt.xlabel("Epoch")
plt.ylabel("loss")
plt.legend()
plt.xticks([1,2,3,4,5])

plt.show()
plt.savefig('train_error.png')
plt.savefig('training and val error.png')

"""## Evaluate on Test Data"""

predictions = eval(test_dataloader,model,3,loss,True)

test_inputs = test_df.input.tolist()

submission_pd = pd.DataFrame({'input': test_inputs,'labels':predictions})

submission_pd.to_csv('final_submission.csv')
