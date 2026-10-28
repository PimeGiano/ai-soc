#pragma once
#include <array>
#include <vector>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <cstdint>
#include <cstring>
struct Memory {
 std::vector<uint8_t> code=std::vector<uint8_t>(65536,0),data=std::vector<uint8_t>(64*1024*1024,0);
 uint8_t& at(uint32_t a){if(a<code.size())return code[a];if(a>=0x01000000 && uint64_t(a)<0x05000000)return data[a-0x01000000];throw std::runtime_error("unmapped memory "+std::to_string(a));}
 uint32_t read(uint32_t a){uint32_t v=0;for(int i=0;i<4;i++)v|=uint32_t(at(a+i))<<(8*i);return v;}
 void write(uint32_t a,uint32_t v,uint8_t st){for(int i=0;i<4;i++)if(st&(1<<i))at(a+i)=uint8_t(v>>(8*i));}
 void load(const std::string&p){std::ifstream f(p,std::ios::binary);if(!f)throw std::runtime_error("open "+p);uint32_t n;f.read((char*)&n,4);for(uint32_t i=0;i<n;i++){uint32_t a,l;f.read((char*)&a,4);f.read((char*)&l,4);for(uint32_t j=0;j<l;j++){char c;f.get(c);at(a+j)=uint8_t(c);}}if(!f)throw std::runtime_error("truncated memory image");}
 void compare(uint32_t a,size_t n,const std::string&p){std::ifstream f(p,std::ios::binary);if(!f)throw std::runtime_error("open reference");for(size_t i=0;i<n;i++){char c;f.get(c);if(!f || at(a+i)!=uint8_t(c))throw std::runtime_error("mismatch byte "+std::to_string(i)+" at "+std::to_string(a)+" got "+std::to_string(int8_t(at(a+i)))+" expected "+std::to_string(int8_t(c)));}}
};
